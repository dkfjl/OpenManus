import argparse
import asyncio
import time
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.enhanced_schema import EnhancedOutlineResponse, EnhancedOutlineStatus
from app.logger import logger
from app.schema import FileUploadResponse
from app.services import run_manus_flow
from app.services.enhanced_outline_storage import enhanced_outline_storage
from app.services.execution_log_service import (
    end_execution_log,
    log_execution_event,
    start_execution_log,
)
from app.services.file_upload_service import (
    file_upload_service,
    get_file_contents_by_uuids,
)
from app.services.ppt_outline_service import generate_ppt_outline_with_format
from app.services.report_generation_service import generate_report_from_steps
from app.utils.async_tasks import get_enhanced_outline_status

app = FastAPI(title="OpenManus Service", version="1.0.0")
_service_lock: Optional[asyncio.Lock] = None


class RunRequest(BaseModel):
    prompt: str = Field(..., description="任务提示内容")
    allow_interactive_fallback: bool = Field(
        default=False,
        description="是否在缺少 prompt 时回退到交互输入（HTTP 接口默认关闭）",
    )


class RunResponse(BaseModel):
    status: str
    result: Optional[str] = None


class DocumentRequest(BaseModel):
    topic: str = Field(..., description="文档主题或题目")
    filepath: Optional[str] = Field(
        default=None, description="可选的存储路径（默认存到 workspace 下）"
    )
    language: Optional[str] = Field(
        default=None, description="输出语言，默认从配置 document.default_language 读取"
    )


class DocumentProgress(BaseModel):
    total_sections: int
    completed_sections: int
    next_section_index: Optional[int] = None
    next_section_heading: Optional[str] = None
    latest_completed_heading: Optional[str] = None


class DocumentResponse(BaseModel):
    task_id: str
    status: str
    filepath: str
    sections: list[str]
    title: str
    progress: DocumentProgress
    execution_log_id: Optional[str] = None
    reference_sources: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None


class ThinkingStepsRequest(BaseModel):
    """思考过程生成请求（接口层定义）"""

    goal: Optional[str] = Field(default=None, description="任务目标或提示，可选")
    count: Optional[int] = Field(
        default=17, description="需要生成的步骤数量，范围15-20"
    )
    format: Optional[str] = Field(default="json", description="输出格式：json/md")


class ReportResult(BaseModel):
    status: str
    filepath: str
    title: str
    agent_summary: Optional[str] = None


class PPTOutlineRequest(BaseModel):
    """PPT大纲生成请求"""

    topic: str = Field(..., description="PPT主题")
    language: str = Field(default="zh", description="输出语言，默认为中文")


class PPTOutlineResponse(BaseModel):
    """PPT大纲生成响应"""

    status: str = Field(..., description="处理状态：success/error")
    outline: List[Dict[str, Any]] = Field(
        default_factory=list, description="PPT大纲项目列表"
    )
    enhanced_outline_status: str = Field(
        default="pending",
        description="增强版大纲状态：pending/processing/completed/failed",
    )
    enhanced_outline_uuid: Optional[str] = Field(
        default=None, description="增强版大纲UUID（状态为completed时提供）"
    )
    topic: str = Field(..., description="PPT主题")
    language: str = Field(..., description="输出语言")
    execution_time: float = Field(..., description="执行时间（秒）")
    reference_sources: List[str] = Field(
        default_factory=list, description="参考文件源列表"
    )


@app.on_event("startup")
async def initialize_services():
    global _service_lock
    _service_lock = asyncio.Lock()

    # 启动异步任务管理的定期清理任务
    from app.utils.async_tasks import start_periodic_cleanup

    cleanup_task = await start_periodic_cleanup()
    if cleanup_task:
        logger.info("Started periodic cleanup task for enhanced outlines")

    logger.info("OpenManus service started, ready to accept requests.")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=RunResponse)
async def run_manus_endpoint(payload: RunRequest) -> RunResponse:
    prompt = payload.prompt.strip()
    log_session = start_execution_log(
        flow_type="manus_flow",
        metadata={
            "entrypoint": "http.run",
            "allow_interactive_fallback": payload.allow_interactive_fallback,
        },
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received /run invocation",
        {"prompt_preview": prompt[:200], "prompt_length": len(prompt)},
    )

    if not prompt:
        log_execution_event(
            "error",
            "Prompt missing for /run",
            {},
        )
        end_execution_log(
            status="failed",
            details={"error": "Prompt must not be empty."},
        )
        log_closed = True
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    if _service_lock is None:
        log_execution_event(
            "error",
            "Service lock missing",
            {"detail": "Service initializing"},
        )
        end_execution_log(status="failed", details={"error": "Service initializing"})
        log_closed = True
        raise HTTPException(
            status_code=503, detail="Service is initializing, please retry."
        )

    if _service_lock.locked():
        log_execution_event(
            "error",
            "Service busy",
            {},
        )
        end_execution_log(
            status="failed",
            details={"error": "Agent busy"},
        )
        log_closed = True
        raise HTTPException(
            status_code=409, detail="Agent is already processing another request."
        )

    try:
        async with _service_lock:
            result = await run_manus_flow(
                prompt=prompt,
                allow_interactive_fallback=payload.allow_interactive_fallback,
            )
        log_execution_event(
            "workflow",
            "run_manus_flow completed",
            {
                "result_length": len(result or ""),
                "result_preview": (result or "")[:200],
            },
        )
        end_execution_log(
            status="completed",
            details={"result_length": len(result or "")},
        )
        log_closed = True
        return RunResponse(status="completed", result=result)
    except HTTPException as exc:
        log_execution_event(
            "error",
            "HTTP error during /run",
            {"status_code": exc.status_code, "detail": exc.detail},
        )
        end_execution_log(
            status="failed",
            details={"status_code": exc.status_code, "detail": exc.detail},
        )
        log_closed = True
        raise
    except Exception as exc:
        log_execution_event(
            "error",
            "Unexpected failure during /run",
            {"error": str(exc)},
        )
        end_execution_log(status="failed", details={"error": str(exc)})
        log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()


@app.post("/api/docx/generate", response_model=ReportResult)
async def generate_report_endpoint(
    topic: str = Form(..., description="报告主题"),
    language: Optional[str] = Form(default=None, description="输出语言，例如 zh/EN 等"),
    file_uuids: Optional[str] = Form(
        default=None,
        description="已上传文件的UUID列表，用逗号分隔，例如: uuid1,uuid2,uuid3",
    ),
) -> ReportResult:
    log_session = start_execution_log(
        flow_type="report_generation",
        metadata={
            "topic": topic,
            "language": language,
        },
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received /api/docx/generate request",
        {
            "topic_preview": topic[:120],
            "language": language,
        },
    )
    try:
        t0 = time.perf_counter()
        if not topic.strip():
            raise HTTPException(status_code=400, detail="topic 不能为空")

        # Process file references via UUIDs (similar to /api/ppt-outline/generate)
        parsed_content = ""
        reference_sources: list[str] = []

        if file_uuids:
            try:
                # Parse UUID string to list
                uuid_list = [
                    uuid_str.strip()
                    for uuid_str in file_uuids.split(",")
                    if uuid_str.strip()
                ]

                if len(uuid_list) > 5:
                    raise HTTPException(status_code=400, detail="最多支持引用5个文件")

                if uuid_list:
                    # Get file content summaries by UUIDs
                    parsed_content = await get_file_contents_by_uuids(uuid_list)

                    # Get file info for reference sources
                    for uuid_str in uuid_list:
                        file_info = file_upload_service.get_file_info_by_uuid(
                            uuid_str.strip()
                        )
                        if file_info:
                            reference_sources.append(file_info.original_name)
                        else:
                            reference_sources.append(f"UUID文件{uuid_str}")

                    log_execution_event(
                        "document_upload",
                        "File references processed via UUIDs",
                        {
                            "uuid_count": len(uuid_list),
                            "reference_sources": reference_sources,
                            "content_length": len(parsed_content or ""),
                        },
                    )

            except Exception as e:
                logger.warning(f"UUID文件处理失败，将继续无参考材料生成: {str(e)}")
                parsed_content = ""
                reference_sources = []
        else:
            log_execution_event(
                "document_upload",
                "No file references provided",
                {},
            )

        # Only generate DOCX format
        t_d0 = time.perf_counter()
        log_execution_event(
            "report_generation",
            "DOCX generation started",
            {
                "language": language,
                "has_reference": bool(parsed_content.strip()),
                "reference_length": len(parsed_content or ""),
                "reference_sources": len(reference_sources or []),
            },
        )
        result = await generate_report_from_steps(
            topic=topic.strip(),
            language=language,
            fmt="docx",
            reference_content=parsed_content,
            reference_sources=reference_sources,
        )
        log_execution_event(
            "report_generation",
            "DOCX generation finished",
            {
                "status": result.get("status"),
                "filepath": result.get("filepath"),
                "duration_sec": round(time.perf_counter() - t_d0, 3),
            },
        )
        log_execution_event(
            "workflow",
            "Report generated",
            {
                "filepath": result.get("filepath"),
                "title": result.get("title"),
                "total_duration_sec": round(time.perf_counter() - t0, 3),
            },
        )
        end_execution_log(
            status="completed",
            details={
                "filepath": result.get("filepath"),
                "total_duration_sec": round(time.perf_counter() - t0, 3),
            },
        )
        log_closed = True
        return ReportResult(**result)
    except HTTPException as exc:
        log_execution_event(
            "error",
            "HTTP error during /api/docx/generate",
            {"status_code": exc.status_code, "detail": exc.detail},
        )
        end_execution_log(
            status="failed",
            details={"status_code": exc.status_code, "detail": exc.detail},
        )
        log_closed = True
        raise
    except Exception as exc:
        log_execution_event(
            "error",
            "Unexpected failure during /api/docx/generate",
            {"error": str(exc)},
        )
        end_execution_log(status="failed", details={"error": str(exc)})
        log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()


@app.post("/api/ppt-outline/generate", response_model=PPTOutlineResponse)
async def generate_ppt_outline_endpoint(
    topic: str = Form(..., description="PPT主题"),
    language: Optional[str] = Form(default="zh", description="输出语言，例如 zh/en"),
    file_uuids: Optional[str] = Form(
        default=None,
        description="已上传文件的UUID列表，用逗号分隔，例如: uuid1,uuid2,uuid3",
    ),
) -> PPTOutlineResponse:
    """
    生成符合指定JSON格式的PPT大纲

    该接口会：
    1. 解析上传的参考文件（如果有）
    2. 调用LLM生成PPT制作过程大纲
    3. 返回结构化的JSON格式大纲数据
    """
    start_time = time.time()

    try:
        # 验证输入参数
        if not topic.strip():
            raise HTTPException(status_code=400, detail="PPT主题不能为空")

        # 处理UUID对应的文件
        reference_content = ""
        reference_sources = []

        if file_uuids:
            try:
                # 解析UUID字符串为列表
                uuid_list = [
                    uuid_str.strip()
                    for uuid_str in file_uuids.split(",")
                    if uuid_str.strip()
                ]

                if len(uuid_list) > 5:
                    raise HTTPException(status_code=400, detail="最多支持引用5个文件")

                if uuid_list:
                    # 根据UUID获取文件内容摘要
                    reference_content = await get_file_contents_by_uuids(uuid_list)

                    # 获取文件信息用于记录源
                    for uuid_str in uuid_list:
                        file_info = file_upload_service.get_file_info_by_uuid(
                            uuid_str.strip()
                        )
                        if file_info:
                            reference_sources.append(file_info.original_name)
                        else:
                            reference_sources.append(f"UUID文件{uuid_str}")

            except Exception as e:
                logger.warning(f"UUID文件处理失败，将继续无参考材料生成: {str(e)}")
                reference_content = ""
                reference_sources = []

        # 调用PPT大纲生成服务
        result = await generate_ppt_outline_with_format(
            topic=topic.strip(),
            language=language or "zh",
            reference_content=reference_content,
            reference_sources=reference_sources,
            generate_enhanced=True,  # 启用增强版大纲生成
        )

        execution_time = time.time() - start_time

        # 构建响应 - 将PPTOutlineItem对象转换为字典
        outline_dicts = []
        if result["outline"]:
            for item in result["outline"]:
                if hasattr(item, "model_dump"):
                    outline_dicts.append(item.model_dump())
                elif hasattr(item, "dict"):
                    outline_dicts.append(item.dict())
                else:
                    # 如果已经是字典，直接使用
                    outline_dicts.append(item)

        return PPTOutlineResponse(
            status=result["status"],
            outline=outline_dicts,
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


@app.get("/api/ppt-outline/enhanced/{uuid}", response_model=EnhancedOutlineResponse)
async def get_enhanced_outline_endpoint(uuid: str) -> EnhancedOutlineResponse:
    """
    获取增强版PPT大纲

    该接口用于获取之前异步生成的增强版PPT大纲内容。

    Args:
        uuid: 增强版大纲的唯一标识符

    Returns:
        EnhancedOutlineResponse: 包含增强版大纲的响应

    Raises:
        HTTPException: 当大纲不存在或生成失败时
    """
    try:
        # 获取增强版大纲状态信息
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

        # 状态为completed，获取大纲内容
        enhanced_outline = await enhanced_outline_storage.get_outline(uuid)

        if enhanced_outline is None:
            # 理论上不应该发生，但做容错处理
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


@app.get("/api/ppt-outline/enhanced/{uuid}/status")
async def get_enhanced_outline_status_endpoint(uuid: str):
    """
    获取增强版PPT大纲状态

    该接口用于查询增强版大纲的生成状态，不返回具体内容。

    Args:
        uuid: 增强版大纲的唯一标识符

    Returns:
        包含状态信息的响应
    """
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


def _get_status_message(status: str) -> str:
    """获取状态对应的消息"""
    status_messages = {
        "pending": "增强版大纲等待生成中",
        "processing": "增强版大纲正在生成中",
        "completed": "增强版大纲已生成完成",
        "failed": "增强版大纲生成失败",
        "not_found": "增强版大纲未找到",
    }
    return status_messages.get(status, "未知状态")


@app.get("/api/ppt-outline/enhanced")
async def list_enhanced_outlines(
    status: Optional[str] = None, limit: int = 50, offset: int = 0
):
    """
    列出增强版PPT大纲

    该接口用于查询系统中所有的增强版大纲记录。

    Args:
        status: 过滤状态（pending/processing/completed/failed）
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        包含大纲列表的响应
    """
    try:
        # 获取所有大纲信息
        all_outlines = enhanced_outline_storage.get_all_outlines()

        # 按状态过滤
        if status:
            filtered_outlines = [
                outline for outline in all_outlines if outline["status"] == status
            ]
        else:
            filtered_outlines = all_outlines

        # 应用分页
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


@app.post("/api/files/upload", response_model=FileUploadResponse)
async def upload_files_endpoint(
    upload_files: List[UploadFile] = File(..., description="上传的文件，最多5个")
) -> FileUploadResponse:
    """
    文件上传接口

    接收最多5个文件，保存到本地并生成UUID前缀，返回UUID列表

    Returns:
        FileUploadResponse: 包含上传文件的UUID和文件信息
    """
    try:
        if not upload_files:
            return FileUploadResponse(
                status="error", uuids=[], files=[], message="没有上传文件"
            )

        if len(upload_files) > 5:
            return FileUploadResponse(
                status="error",
                uuids=[],
                files=[],
                message="上传文件数量超过限制，最多支持5个文件",
            )

        # 调用文件上传服务
        result = await file_upload_service.upload_files(upload_files)
        return result

    except Exception as e:
        logger.error(f"文件上传接口错误: {str(e)}")
        return FileUploadResponse(
            status="error", uuids=[], files=[], message=f"文件上传失败: {str(e)}"
        )


@app.get("/api/files/upload-formats")
async def get_upload_formats():
    """
    获取支持的文件上传格式信息
    """
    return file_upload_service.get_supported_formats()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Manus once via CLI or start the HTTP service."
    )
    parser.add_argument("--prompt", type=str, help="Run once with the given prompt.")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server host.")
    parser.add_argument("--port", type=int, default=10000, help="Server port.")
    return parser.parse_args()


def start_server(host: str, port: int):
    logger.info(f"Starting OpenManus HTTP service on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


def main():
    args = parse_args()

    if args.prompt:
        asyncio.run(
            run_manus_flow(prompt=args.prompt, allow_interactive_fallback=False)
        )
    else:
        start_server(args.host, args.port)


if __name__ == "__main__":
    main()
