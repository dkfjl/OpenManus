"""
Utilities to normalize ThinkChain step results to OutlineItem-like dicts
matching the frontend expectation, while omitting schemaVersion.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import hashlib
import random

# Minimal, local defaults. Can be made configurable later.
MIN_DESC_CHARS = 100
MIN_SUMMARY_CHARS = 100
MIN_DETAIL_CHARS = 100


def _stable_rand_int(seed: str, lo: int, hi: int) -> int:
    """Deterministic integer in [lo, hi] based on stable md5 of seed."""
    if lo > hi:
        lo, hi = hi, lo
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    val = int(digest[:8], 16)
    return lo + (val % (hi - lo + 1))


def _ensure_min_chars(text: str, min_chars: int, scaffold: List[str]) -> str:
    """
    Ensure `text` has at least `min_chars` characters by appending
    coherent sentences built from provided scaffold items.
    """
    text = (text or "").strip()
    if len(text) >= min_chars:
        return text
    extras: List[str] = []
    for s in scaffold:
        s = (s or "").strip()
        if not s:
            continue
        extras.append(s)
        if len(text) + sum(len(x) for x in extras) + len(extras) * 1 >= min_chars:
            break
    if extras:
        joiner = "\n\n" if "\n" in text else "。"
        text = f"{text}{joiner}".strip(joiner)
        text = text + ("\n\n" if joiner == "\n\n" else "") + ("；".join(extras) + "。")
    return text


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
    description = _localized(
        language,
        f"围绕「{topic}」的{step_name}，需要给出可执行要点与产出说明。",
        f"{step_name} for '{topic}', with actionable points and deliverables.",
    )

    summary: Optional[str] = None
    substeps: List[Dict[str, Any]] = []
    # Target substep count derived from a stable per-step seed (3~5)
    SUBSTEP_TARGET = _stable_rand_int(f"{topic}|{step_name}|{step}", 3, 5)

    def add_sub(text: str) -> None:
        nonlocal substeps
        text = (text or "").strip()
        if not text:
            return
        if len(substeps) >= SUBSTEP_TARGET:
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
        if len(substeps) >= SUBSTEP_TARGET:
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
                        if len(substeps) >= SUBSTEP_TARGET:
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

    # Prefer meta from model output if present
    if isinstance(content, dict) and isinstance(content.get("meta"), dict):
        meta_dict = content.get("meta")
        cand_summary = meta_dict.get("summary")
        if isinstance(cand_summary, str) and cand_summary.strip():
            summary = cand_summary.strip()
        cand_substeps = meta_dict.get("substeps")
        if isinstance(cand_substeps, list) and cand_substeps:
            # Normalize provided substeps structure
            normalized: List[Dict[str, Any]] = []
            for idx, it in enumerate(cand_substeps, start=1):
                if not isinstance(it, dict):
                    continue
                txt = str(it.get("text") or it.get("title") or it.get("name") or f"子项{idx}")
                show = bool(it.get("showDetail", False))
                dtype = it.get("detailType") if show else None
                dp = it.get("detailPayload") if show else None
                normalized.append(
                    {
                        "key": f"{step}-{len(normalized) + 1}",
                        "text": txt[:160],
                        "showDetail": show,
                        "detailType": dtype if isinstance(dtype, str) else None,
                        "detailPayload": dp if isinstance(dp, dict) else None,
                    }
                )
            # Merge with auto-extracted ones to ensure diversity
            if normalized:
                substeps = normalized

    if not summary:
        summary = _localized(
            language,
            f"{step_name}：围绕「{topic}」梳理关键要点、实施路径与产出形式，确保结果可检查、可交付。",
            f"{step_name}: Organize key points, execution path and deliverables for '{topic}', ensuring verifiability.",
        )

    if not substeps:
        placeholders = (
            [f"{step_name}—要点1", f"{step_name}—要点2", f"{step_name}—要点3"]
            if (language or "zh").lower().startswith("zh")
            else [f"{step_name} - point 1", f"{step_name} - point 2", f"{step_name} - point 3"]
        )
        for txt in placeholders:
            add_sub(txt)

    # Adjust to target count (fill or trim)
    if len(substeps) < SUBSTEP_TARGET:
        # Fill placeholders to reach target
        i = 1
        while len(substeps) < SUBSTEP_TARGET and i <= 5:
            add_sub(f"{step_name}—补充要点{i}")
            i += 1

    if len(substeps) > SUBSTEP_TARGET:
        substeps = substeps[:SUBSTEP_TARGET]

    # Enforce detail visibility and restrict types to {text, list, table}
    allowed_types = ["text", "list", "table"]

    text_count = 0
    detail_count = 0

    # Ensure description and summary meet minimum length
    base_scaffold = [s.get("text", "") for s in substeps][:3]
    description = _ensure_min_chars(description, MIN_DESC_CHARS, base_scaffold)
    summary = _ensure_min_chars(summary or description, MIN_SUMMARY_CHARS, base_scaffold)

    base_text = summary or description or title

    for idx, s in enumerate(substeps, start=1):
        # 强制展示细节
        s["showDetail"] = True
        detail_count += 1

        # 依据内容推断类型，但严格限定到 {text, list, table}
        inferred = _infer_detail_type_from_text(base_text)
        if inferred not in allowed_types:
            inferred = "list"
        # 控制 text 类型最多 1 个
        if inferred == "text" and text_count >= 1:
            inferred = "list"
        dt = inferred
        if dt == "text":
            text_count += 1
        s["detailType"] = dt

        heading = s.get("text") or title
        if dt == "text":
            md_core = f"{base_text}\n\n- 关键行动：明确里程碑与责任分工\n- 实施要点：聚焦依赖与风险缓释\n- 评估指标：以结果与过程双维度校验"
            md = f"### {heading}\n\n{_ensure_min_chars(md_core, MIN_DETAIL_CHARS, base_scaffold)}"
        elif dt == "list":
            md_core = (
                f"- 背景：{base_text}\n"
                "- 步骤：分解为3~5个可执行任务\n"
                "- 工具：给出方法与模板\n"
                "- 风险：列出主要阻碍与规避策略\n"
                "- 产出：定义交付件与验收标准"
            )
            md = f"### {heading}\n\n{_ensure_min_chars(md_core, MIN_DETAIL_CHARS, base_scaffold)}"
        else:  # table
            table = (
                "| 条目 | 说明 |\n|---|---|\n"
                f"| 主要内容 | {base_text} |\n"
                "| 实施步骤 | 3~5个动作，各自有负责人与时间点 |\n"
                "| 风险与对策 | 标注优先级与缓解手段 |\n"
                "| 交付与验收 | 明确格式、完成定义与评估方式 |"
            )
            md = f"### {heading}\n\n{_ensure_min_chars(table, MIN_DETAIL_CHARS, base_scaffold)}"
        s["detailPayload"] = {"format": "markdown", "content": md}

    return {
        "key": str(step),
        "title": title,
        "description": description,
        "detailType": "text",
        "meta": {"summary": summary, "substeps": substeps},
    }
