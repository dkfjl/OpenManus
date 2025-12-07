import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Form, HTTPException

from app.enhanced_schema import EnhancedOutlineResponse, EnhancedOutlineStatus
from app.logger import logger
from app.services.enhanced_outline_storage import enhanced_outline_storage
from app.services.file_upload_service import (
    file_upload_service,
    get_file_contents_by_uuids,
)
from app.services.ppt_outline_service import generate_ppt_outline_with_format
from app.services.outline_state_engine import outline_state_engine
from app.utils.async_tasks import get_enhanced_outline_status, create_enhanced_outline_task

from app.schemas.ppt_outline import PPTOutlineResponse

router = APIRouter()


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
                        file_info = file_upload_service.get_file_info_by_uuid(uuid_str.strip())
                        reference_sources.append(
                            file_info.original_name if file_info else f"UUID文件{uuid_str}"
                        )
            except Exception as e:
                logger.warning(f"UUID文件处理失败，将继续无参考材料生成: {str(e)}")
                reference_content = ""
                reference_sources = []

        # 自收敛模式：通过状态引擎推动一步并返回
        if (mode or "legacy").lower() == "convergent":
            step_result, is_completed, new_session_id = await outline_state_engine.process_request(
                topic=topic.strip(),
                session_id=session_id,
                language=language or "zh",
                reference_content=reference_content,
                reference_sources=reference_sources,
            )

            execution_time = time.time() - start_time
            # 收敛时自动触发增强版生成
            enhanced_uuid = None
            enhanced_status = EnhancedOutlineStatus.PENDING
            if is_completed:
                try:
                    enhanced_uuid = await enhanced_outline_storage.create_outline_record(
                        topic=topic.strip(), language=language or "zh", reference_sources=reference_sources
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
                    logger.error(f"Failed to start enhanced outline (convergent): {str(e)}")
                    enhanced_status = EnhancedOutlineStatus.FAILED

            return PPTOutlineResponse(
                status="success",
                outline=[step_result],
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
            raise HTTPException(status_code=500, detail=f"获取增强版大纲失败: {status_info.get('error_message', '未知错误')}")
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
            raise HTTPException(status_code=500, detail=f"查询状态失败: {status_info.get('error_message', '未知错误')}")
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
async def list_enhanced_outlines(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    try:
        all_outlines = enhanced_outline_storage.get_all_outlines()
        filtered_outlines = (
            [o for o in all_outlines if o["status"] == status] if status else all_outlines
        )
        total_count = len(filtered_outlines)
        paginated_outlines = filtered_outlines[offset : offset + limit]
        return {"total_count": total_count, "outlines": paginated_outlines, "limit": limit, "offset": offset}
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
