import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Form, HTTPException

from app.enhanced_schema import EnhancedOutlineResponse, EnhancedOutlineStatus
from app.logger import logger
from app.schemas.ppt_outline import PPTOutlineResponse
from app.services.enhanced_outline_storage import enhanced_outline_storage
from app.services.file_upload_service import (
    file_upload_service,
    get_file_contents_by_uuids,
)
from app.services.outline_state_engine import outline_state_engine
from app.services.ppt_outline_service import generate_ppt_outline_with_format
from app.utils.async_tasks import (
    create_enhanced_outline_task,
    get_enhanced_outline_status,
)

router = APIRouter()


def _normalize_convergent_step_to_outline_item(
    step_result: Dict[str, Any], *, topic: str, language: str
) -> Dict[str, Any]:
    """
    将状态引擎单步结果规范化为前端需要的 PPTOutlineItem 结构。
    约定：
    - key 从 0 开始，使用 step 作为字符串
    - title 使用 step_name（保持结构为主）
    - description/summary 做轻量本地化
    - substeps 优先从 content 的 chapters/items/sections/points 提取
    - 在“最终完善与总结”收敛步，同样返回一个 PPTOutlineItem
    """

    def _localized_text(zh: str, en: str) -> str:
        return zh if (language or "zh").lower().startswith("zh") else en

    step = int(step_result.get("step", 0))
    step_name = str(step_result.get("step_name") or f"步骤{step}")
    content = step_result.get("content", {})

    title = step_name
    description = _localized_text(
        f"围绕「{topic}」的{step_name}。",
        f"{step_name} for '{topic}'.",
    )

    # 提取 summary 与 substeps
    summary: Optional[str] = None
    substeps: List[Dict[str, Any]] = []
    # 每个步骤最多 5 个子步骤
    SUBSTEP_CAP = 5

    def add_substep(
        text: str,
        *,
        show_detail: bool = False,
        detail_type: Optional[str] = None,
        detail_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        text = (text or "").strip()
        if not text:
            return
        if len(substeps) >= SUBSTEP_CAP:
            return
        substeps.append(
            {
                "key": f"{step}-{len(substeps) + 1}",
                "text": text[:160],
                # showDetail 将在最终阶段统一设置（参考 thinking_steps 规则）
                "showDetail": False,
                # 始终输出 detailType/detailPayload（即便为 null）
                "detailType": None,
                "detailPayload": None,
            }
        )

    def traverse_extract(obj: Any) -> None:
        if len(substeps) >= SUBSTEP_CAP:
            return
        if isinstance(obj, dict):
            nonlocal summary
            # 直接命中的 summary 字段
            if summary is None and isinstance(obj.get("summary"), str):
                cand = obj.get("summary", "").strip()
                if cand:
                    summary = cand

            # 优先解析章节/条目结构
            if isinstance(obj.get("chapters"), list):
                for ch in obj.get("chapters", []):
                    if isinstance(ch, dict):
                        if isinstance(ch.get("title"), str):
                            # 章节标题作为一个子步骤（无详情）
                            add_substep(ch.get("title"))
                        items = ch.get("items")
                        if isinstance(items, list):
                            for it in items:
                                if isinstance(it, dict):
                                    point_txt = (
                                        it.get("point")
                                        or it.get("title")
                                        or it.get("text")
                                    )
                                    if isinstance(point_txt, str):
                                        add_substep(point_txt)
                                elif isinstance(it, str):
                                    add_substep(it)
                    elif isinstance(ch, str):
                        add_substep(ch)

            # items / points 直接为列表时
            if isinstance(obj.get("items"), list):
                for it in obj.get("items", []):
                    if isinstance(it, dict):
                        txt = it.get("point") or it.get("title") or it.get("text")
                        if isinstance(txt, str):
                            add_substep(txt)
                    elif isinstance(it, str):
                        add_substep(it)

            if isinstance(obj.get("points"), list):
                for it in obj.get("points", []):
                    if isinstance(it, dict):
                        txt = it.get("title") or it.get("text")
                        if isinstance(txt, str):
                            add_substep(txt)
                    elif isinstance(it, str):
                        add_substep(it)

            # 递归遍历其它字段，避免对已处理键（chapters/items/points/summary）重复处理
            for k, v in obj.items():
                if k in {"chapters", "items", "points", "summary"}:
                    continue
                traverse_extract(v)
        elif isinstance(obj, list):
            for el in obj:
                traverse_extract(el)
        elif isinstance(obj, str):
            # 从纯文本中粗抽要点（前几行非空文本）
            if len(substeps) < 3:
                lines = [ln.strip("-•* \t") for ln in obj.splitlines() if ln.strip()]
                for ln in lines:
                    if len(ln) >= 6:
                        add_substep(ln)
                        if len(substeps) >= SUBSTEP_CAP:
                            break

    # 收敛步：content 结构为 {"summary": {...或str}, "final": <任意>}
    if isinstance(content, dict) and "final" in content:
        summ = content.get("summary")
        if isinstance(summ, str) and summ.strip():
            summary = summ.strip()
        elif isinstance(summ, dict):
            total = summ.get("total_steps")
            avg = summ.get("avg_quality")
            summary = _localized_text(
                f"已收敛，共 {total} 步，平均质量 {avg}。",
                f"Converged after {total} steps, average quality {avg}.",
            )
        traverse_extract(content.get("final"))
    else:
        traverse_extract(content)

    if not summary:
        summary = _localized_text(
            f"{step_name}：围绕「{topic}」梳理关键要点。",
            f"{step_name}: Key points for '{topic}'.",
        )

    if not substeps:
        # 无结构时的保底子步骤
        placeholders = (
            [f"{step_name}—要点1", f"{step_name}—要点2", f"{step_name}—要点3"]
            if (language or "zh").lower().startswith("zh")
            else [
                f"{step_name} - point 1",
                f"{step_name} - point 2",
                f"{step_name} - point 3",
            ]
        )
        for txt in placeholders:
            add_substep(txt)

    # 截断到最多 5 条
    if len(substeps) > SUBSTEP_CAP:
        substeps = substeps[:SUBSTEP_CAP]

    # 仅参照 thinking_steps 的规则设置 showDetail：偶数项 True，其它 False
    allowed_types = ["table", "image", "list", "code", "diagram"]
    for idx, s in enumerate(substeps, start=1):
        s["showDetail"] = idx % 2 == 0
        if s["showDetail"]:
            # detailType 优先使用现有且在允许列表内，否则按轮询分配
            dt_existing = s.get("detailType")
            dt = (
                dt_existing
                if isinstance(dt_existing, str) and dt_existing in allowed_types
                else allowed_types[(idx - 1) % len(allowed_types)]
            )
            s["detailType"] = dt
            # detailPayload：若不存在或类型不在允许范围，按 dt 填充一个最小可用的数据包
            payload = s.get("detailPayload") or {}
            ptype = payload.get("type") if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or ptype not in allowed_types:
                base = summary or description or title
                heading = s.get("text") or title
                data = f"### {heading}\n{base}"
                s["detailPayload"] = {"type": dt, "data": data}

    return {
        "key": str(step),  # 0 基
        "title": title,
        "description": description,
        "detailType": "markdown",
        "meta": {"summary": summary, "substeps": substeps},
    }


@router.post("/api/ppt-outline/generate", response_model=PPTOutlineResponse)
async def generate_ppt_outline_endpoint(
    topic: str = Form(..., description="PPT主题"),
    language: Optional[str] = Form(default="zh", description="输出语言，例如 zh/en"),
    file_uuids: Optional[str] = Form(
        default=None,
        description="已上传文件的UUID列表，用逗号分隔，例如: uuid1,uuid2,uuid3",
    ),
    session_id: Optional[str] = Form(
        default=None, description="自收敛模式：会话ID，首次请求不传"
    ),
    mode: Optional[str] = Form(
        default="legacy",
        description="运行模式：legacy(默认，单次生成) / convergent(自收敛轮询)",
    ),
) -> PPTOutlineResponse:
    start_time = time.time()
    try:
        if not topic.strip():
            raise HTTPException(status_code=400, detail="PPT主题不能为空")

        reference_content = ""
        reference_sources: List[str] = []

        if file_uuids:
            try:
                uuid_list = [u.strip() for u in file_uuids.split(",") if u.strip()]
                if len(uuid_list) > 5:
                    raise HTTPException(status_code=400, detail="最多支持引用5个文件")
                if uuid_list:
                    reference_content = await get_file_contents_by_uuids(uuid_list)
                    for uuid_str in uuid_list:
                        file_info = file_upload_service.get_file_info_by_uuid(
                            uuid_str.strip()
                        )
                        reference_sources.append(
                            file_info.original_name
                            if file_info
                            else f"UUID文件{uuid_str}"
                        )
            except Exception as e:
                logger.warning(f"UUID文件处理失败，将继续无参考材料生成: {str(e)}")
                reference_content = ""
                reference_sources = []

        # 自收敛模式：通过状态引擎推动一步并返回
        if (mode or "legacy").lower() == "convergent":
            step_result, is_completed, new_session_id = (
                await outline_state_engine.process_request(
                    topic=topic.strip(),
                    session_id=session_id,
                    language=language or "zh",
                    reference_content=reference_content,
                    reference_sources=reference_sources,
                )
            )

            execution_time = time.time() - start_time
            # 收敛时自动触发增强版生成
            enhanced_uuid = None
            enhanced_status = EnhancedOutlineStatus.PENDING
            if is_completed:
                try:
                    enhanced_uuid = (
                        await enhanced_outline_storage.create_outline_record(
                            topic=topic.strip(),
                            language=language or "zh",
                            reference_sources=reference_sources,
                        )
                    )
                    # 这里 original_outline 简化为空列表；增强版生成逻辑主要依赖 topic/language/reference_content
                    await create_enhanced_outline_task(
                        original_outline=[],
                        topic=topic.strip(),
                        language=language or "zh",
                        reference_content=reference_content,
                        reference_sources=reference_sources,
                        enhanced_uuid=enhanced_uuid,
                    )
                    enhanced_status = EnhancedOutlineStatus.PROCESSING
                except Exception as e:
                    logger.error(
                        f"Failed to start enhanced outline (convergent): {str(e)}"
                    )
                    enhanced_status = EnhancedOutlineStatus.FAILED

            # 规范化为单个 PPTOutlineItem 字典返回
            normalized_item = _normalize_convergent_step_to_outline_item(
                step_result,
                topic=topic.strip(),
                language=language or "zh",
            )

            return PPTOutlineResponse(
                status="success",
                outline=[normalized_item],
                session_id=new_session_id,
                is_completed=is_completed,
                enhanced_outline_status=enhanced_status,
                enhanced_outline_uuid=enhanced_uuid,
                topic=topic.strip(),
                language=language or "zh",
                execution_time=execution_time,
                reference_sources=reference_sources,
            )

        # 兼容旧模式：一次性生成 + 异步增强版
        result = await generate_ppt_outline_with_format(
            topic=topic.strip(),
            language=language or "zh",
            reference_content=reference_content,
            reference_sources=reference_sources,
            generate_enhanced=True,
        )

        execution_time = time.time() - start_time

        outline_dicts: List[Dict[str, Any]] = []
        if result["outline"]:
            for item in result["outline"]:
                if hasattr(item, "model_dump"):
                    outline_dicts.append(item.model_dump())
                elif hasattr(item, "dict"):
                    outline_dicts.append(item.dict())
                else:
                    outline_dicts.append(item)

        return PPTOutlineResponse(
            status=result["status"],
            outline=outline_dicts,
            session_id=None,
            is_completed=None,
            enhanced_outline_status=result["enhanced_outline_status"],
            enhanced_outline_uuid=result["enhanced_outline_uuid"],
            topic=result["topic"],
            language=result["language"],
            execution_time=execution_time,
            reference_sources=result["reference_sources"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PPT大纲生成接口错误: {str(e)}")
        execution_time = time.time() - start_time
        raise HTTPException(status_code=500, detail=f"PPT大纲生成失败: {str(e)}")


@router.get("/api/ppt-outline/enhanced/{uuid}", response_model=EnhancedOutlineResponse)
async def get_enhanced_outline_endpoint(uuid: str) -> EnhancedOutlineResponse:
    try:
        status_info = await get_enhanced_outline_status(uuid)

        if status_info["status"] == "not_found":
            raise HTTPException(status_code=404, detail="增强版大纲未找到")
        if status_info["status"] == "error":
            raise HTTPException(
                status_code=500,
                detail=f"获取增强版大纲失败: {status_info.get('error_message', '未知错误')}",
            )
        if status_info["status"] == EnhancedOutlineStatus.FAILED:
            error_msg = status_info.get("error_message", "增强版大纲生成失败")
            return EnhancedOutlineResponse(
                status="failed",
                outline=None,
                topic=status_info["topic"],
                language=status_info["language"],
                created_at=status_info["created_at"],
                reference_sources=status_info["reference_sources"],
                message=f"增强版大纲生成失败: {error_msg}",
            )
        if status_info["status"] == EnhancedOutlineStatus.PROCESSING:
            return EnhancedOutlineResponse(
                status="processing",
                outline=None,
                topic=status_info["topic"],
                language=status_info["language"],
                created_at=status_info["created_at"],
                reference_sources=status_info["reference_sources"],
                message="增强版大纲正在生成中，请稍后再试",
            )
        if status_info["status"] == EnhancedOutlineStatus.PENDING:
            return EnhancedOutlineResponse(
                status="pending",
                outline=None,
                topic=status_info["topic"],
                language=status_info["language"],
                created_at=status_info["created_at"],
                reference_sources=status_info["reference_sources"],
                message="增强版大纲等待生成中",
            )

        enhanced_outline = await enhanced_outline_storage.get_outline(uuid)
        if enhanced_outline is None:
            return EnhancedOutlineResponse(
                status="processing",
                outline=None,
                topic=status_info["topic"],
                language=status_info["language"],
                created_at=status_info["created_at"],
                reference_sources=status_info["reference_sources"],
                message="增强版大纲内容尚未准备好，请稍后再试",
            )

        return EnhancedOutlineResponse(
            status="success",
            outline=enhanced_outline,
            topic=status_info["topic"],
            language=status_info["language"],
            created_at=status_info["created_at"],
            reference_sources=status_info["reference_sources"],
            message="增强版大纲获取成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get enhanced outline {uuid}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取增强版大纲失败: {str(e)}")


@router.get("/api/ppt-outline/enhanced/{uuid}/status")
async def get_enhanced_outline_status_endpoint(uuid: str):
    try:
        status_info = await get_enhanced_outline_status(uuid)
        if status_info["status"] == "not_found":
            raise HTTPException(status_code=404, detail="增强版大纲未找到")
        if status_info["status"] == "error":
            raise HTTPException(
                status_code=500,
                detail=f"查询状态失败: {status_info.get('error_message', '未知错误')}",
            )
        return {
            "uuid": uuid,
            "status": status_info["status"],
            "topic": status_info["topic"],
            "language": status_info["language"],
            "created_at": status_info["created_at"],
            "updated_at": status_info["updated_at"],
            "reference_sources": status_info["reference_sources"],
            "message": _get_status_message(status_info["status"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get enhanced outline status for {uuid}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询增强版大纲状态失败: {str(e)}")


@router.get("/api/ppt-outline/enhanced")
async def list_enhanced_outlines(
    status: Optional[str] = None, limit: int = 50, offset: int = 0
):
    try:
        all_outlines = enhanced_outline_storage.get_all_outlines()
        filtered_outlines = (
            [o for o in all_outlines if o["status"] == status]
            if status
            else all_outlines
        )
        total_count = len(filtered_outlines)
        paginated_outlines = filtered_outlines[offset : offset + limit]
        return {
            "total_count": total_count,
            "outlines": paginated_outlines,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Failed to list enhanced outlines: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取增强版大纲列表失败: {str(e)}")


def _get_status_message(status: str) -> str:
    status_messages = {
        "pending": "增强版大纲等待生成中",
        "processing": "增强版大纲正在生成中",
        "completed": "增强版大纲已生成完成",
        "failed": "增强版大纲生成失败",
        "not_found": "增强版大纲未找到",
    }
    return status_messages.get(status, "未知状态")
