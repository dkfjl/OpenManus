"""
Utilities to normalize ThinkChain step results to OutlineItem-like dicts
matching the frontend expectation, while omitting schemaVersion.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _localized(language: str, zh: str, en: str) -> str:
    return zh if (language or "zh").lower().startswith("zh") else en


def _infer_detail_type_from_text(text: str) -> str:
    lines = text.split("\n")
    if sum(1 for line in lines if "|" in line) >= 2:
        return "table"
    list_lines = [ln.strip() for ln in lines if ln.strip().startswith(("- ", "* ", "•"))]
    if len(list_lines) >= 2:
        return "list"
    return "text"


def normalize_step_result(
    step_result: Dict[str, Any], *, topic: str, language: str
) -> Dict[str, Any]:
    """Normalize a step_result (from state engine) to OutlineItem-like dict."""
    step = int(step_result.get("step", 0))
    step_name = str(step_result.get("step_name") or f"步骤{step}")
    content = step_result.get("content", {})
    # 专用分支：文件审阅与要点整合
    # 需求：
    # - substeps[*].text = 引用文件名
    # - showDetail = True
    # - detailType = "text"
    # - detailPayload.format = "markdown"
    # - detailPayload.content = 引擎产出的文件摘要 markdown 全文
    # 触发条件：content_type == "file_summary" 或 步骤标题为固定预步骤标题
    content_type = str(step_result.get("content_type") or "")
    is_file_review = (
        content_type == "file_summary"
        or step_name == "[PRE] 文件审阅与要点整合"
    )
    if is_file_review and isinstance(content, dict):
        # 组装 summary
        summary_text = str(content.get("summary") or "").strip()
        if not summary_text:
            summary_text = _localized(
                language,
                f"已完成文件审阅并整合要点。",
                "Files reviewed and key points integrated.",
            )

        # 直接读取引擎产生的 substeps，按要求改写字段
        raw_items = content.get("substeps") or []
        normalized_substeps: List[Dict[str, Any]] = []
        if isinstance(raw_items, list) and raw_items:
            for idx, it in enumerate(raw_items, start=1):
                if not isinstance(it, dict):
                    continue
                file_name = str(it.get("file_name") or it.get("text") or f"file_{idx}")
                # 优先取引擎给的 markdown 全文
                dp = it.get("detailPayload") or {}
                full_md = dp.get("content") if isinstance(dp, dict) else None
                if not isinstance(full_md, str) or not full_md.strip():
                    # 回退：用已有的文本构造一个最小 markdown
                    existing = str(it.get("text") or "").strip()
                    if existing:
                        full_md = f"### {file_name}\n\n{existing}"
                    else:
                        full_md = f"### {file_name}\n\n(暂无摘要内容)"

                normalized_substeps.append(
                    {
                        "key": f"{step}-{idx}",
                        "text": file_name,
                        "showDetail": True,
                        "detailType": "text",
                        "detailPayload": {
                            "format": "markdown",
                            "content": full_md,
                        },
                    }
                )
        else:
            # 冗余兜底：如果没有引擎 substeps，则用 file_list 构建
            file_list = content.get("file_list") or []
            for idx, fname in enumerate(file_list, start=1):
                file_name = str(fname)
                normalized_substeps.append(
                    {
                        "key": f"{step}-{idx}",
                        "text": file_name,
                        "showDetail": True,
                        "detailType": "text",
                        "detailPayload": {
                            "format": "markdown",
                            "content": f"### {file_name}\n\n(暂无摘要内容)",
                        },
                    }
                )

        title = step_name
        description = _localized(
            language,
            f"围绕「{topic}」的{step_name}。",
            f"{step_name} for '{topic}'.",
        )

        return {
            "key": str(step),
            "title": title,
            "description": description,
            "detailType": "text",
            "meta": {"summary": summary_text, "substeps": normalized_substeps},
        }

    # 专用分支：提示词优化与验收标准
    # 需求：
    # - substeps[*].text = 模板名称
    # - showDetail = True
    # - detailType = "list"
    # - detailPayload.format = "markdown"
    # - detailPayload.content = 「修改前」与「修改后」模板内容（Markdown）
    is_prompt_opt = (
        content_type == "prompt_optimization"
        or step_name == "[PRE] 提示词优化与验收标准"
    )
    if is_prompt_opt and isinstance(content, dict):
        summary_text = str(content.get("summary") or "").strip() or _localized(
            language,
            "已完成模板检索与优化。",
            "Completed template retrieval and optimization.",
        )

        normalized_substeps: List[Dict[str, Any]] = []
        items = content.get("substeps") or []
        if isinstance(items, list):
            for idx, it in enumerate(items, start=1):
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or it.get("id") or f"模板{idx}")
                before = str(it.get("before") or "")
                after = str(it.get("after") or before)
                md = (
                    f"### {name}\n\n"
                    f"**修改前（Before）**\n\n{before}\n\n"
                    f"**修改后（After）**\n\n{after}\n"
                )
                normalized_substeps.append(
                    {
                        "key": f"{step}-{idx}",
                        "text": name,
                        "showDetail": True,
                        "detailType": "list",
                        "detailPayload": {"format": "markdown", "content": md},
                    }
                )

        title = step_name
        description = _localized(
            language,
            f"围绕「{topic}」的{step_name}。",
            f"{step_name} for '{topic}'.",
        )

        return {
            "key": str(step),
            "title": title,
            "description": description,
            "detailType": "text",
            "meta": {"summary": summary_text, "substeps": normalized_substeps},
        }

    title = step_name
    description = _localized(language, f"围绕「{topic}」的{step_name}。", f"{step_name} for '{topic}'.")

    summary: Optional[str] = None
    substeps: List[Dict[str, Any]] = []
    SUBSTEP_CAP = 5

    def add_sub(text: str) -> None:
        nonlocal substeps
        text = (text or "").strip()
        if not text:
            return
        if len(substeps) >= SUBSTEP_CAP:
            return
        substeps.append(
            {
                "key": f"{step}-{len(substeps) + 1}",
                "text": text[:160],
                "showDetail": False,
                "detailType": None,
                "detailPayload": None,
            }
        )

    def traverse(obj: Any) -> None:
        if len(substeps) >= SUBSTEP_CAP:
            return
        if isinstance(obj, dict):
            nonlocal summary
            if summary is None and isinstance(obj.get("summary"), str):
                s = obj.get("summary", "").strip()
                if s:
                    summary = s
            for k in ("chapters", "items", "points"):
                if isinstance(obj.get(k), list):
                    for it in obj.get(k, []):
                        if isinstance(it, dict):
                            txt = it.get("point") or it.get("title") or it.get("text")
                            if isinstance(txt, str):
                                add_sub(txt)
                        elif isinstance(it, str):
                            add_sub(it)
            for k, v in obj.items():
                if k in {"chapters", "items", "points", "summary"}:
                    continue
                traverse(v)
        elif isinstance(obj, list):
            for el in obj:
                traverse(el)
        elif isinstance(obj, str):
            if len(substeps) < 3:
                lines = [ln.strip("-•* \t") for ln in obj.splitlines() if ln.strip()]
                for ln in lines:
                    if len(ln) >= 6:
                        add_sub(ln)
                        if len(substeps) >= SUBSTEP_CAP:
                            break

    if isinstance(content, dict) and "final" in content:
        summ = content.get("summary")
        if isinstance(summ, str) and summ.strip():
            summary = summ.strip()
        elif isinstance(summ, dict):
            total = summ.get("total_steps")
            avg = summ.get("avg_quality")
            summary = _localized(
                language,
                f"已收敛，共 {total} 步，平均质量 {avg}。",
                f"Converged after {total} steps, average quality {avg}.",
            )
        traverse(content.get("final"))
    else:
        traverse(content)

    if not summary:
        summary = _localized(
            language,
            f"{step_name}：围绕「{topic}」梳理关键要点。",
            f"{step_name}: Key points for '{topic}'.",
        )

    if not substeps:
        placeholders = (
            [f"{step_name}—要点1", f"{step_name}—要点2", f"{step_name}—要点3"]
            if (language or "zh").lower().startswith("zh")
            else [f"{step_name} - point 1", f"{step_name} - point 2", f"{step_name} - point 3"]
        )
        for txt in placeholders:
            add_sub(txt)

    if len(substeps) > SUBSTEP_CAP:
        substeps = substeps[:SUBSTEP_CAP]

    # even index detail display and diversity
    allowed_types = ["text", "image", "list", "table"]
    non_text_types = ["image", "list", "table"]

    text_count = 0
    detail_count = 0

    base_text = summary or description or title

    for idx, s in enumerate(substeps, start=1):
        s["showDetail"] = idx % 2 == 0
        if s["showDetail"]:
            detail_count += 1
            inferred = _infer_detail_type_from_text(base_text)
            if inferred == "text" and text_count >= 1:
                dt = non_text_types[(detail_count - 1) % len(non_text_types)]
            else:
                dt = inferred
            if dt not in allowed_types:
                dt = non_text_types[(detail_count - 1) % len(non_text_types)]
            if dt == "text":
                text_count += 1
            s["detailType"] = dt
            heading = s.get("text") or title
            if dt == "text":
                md = f"### {heading}\n\n{base_text}"
            elif dt == "list":
                md = f"### {heading}\n\n- {base_text}\n- 详细说明\n- 补充要点"
            elif dt == "table":
                md = (
                    f"### {heading}\n\n| 项目 | 描述 |\n|---|---|\n| 主要内容 | {base_text} |\n| 关键要点 | 详细说明 |"
                )
            else:  # image
                md = f"### {heading}\n\n![{heading}](placeholder.jpg)\n\n> {base_text}"
            s["detailPayload"] = {"format": "markdown", "content": md}
            if dt == "image":
                s["detailPayload"].update(
                    {"imageUrl": "placeholder.jpg", "alt": heading, "caption": base_text}
                )

    return {
        "key": str(step),
        "title": title,
        "description": description,
        "detailType": "text",
        "meta": {"summary": summary, "substeps": substeps},
    }
