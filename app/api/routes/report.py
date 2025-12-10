import time
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Depends

from app.schemas.report import ReportResult
from app.logger import logger
from app.services.execution_log_service import (
    end_execution_log,
    log_execution_event,
    start_execution_log,
)
from app.services.file_upload_service import (
    file_upload_service,
    get_file_contents_by_uuids,
)
from app.services.report_generation_service import generate_report_from_steps

# 导入对象存储相关
from app.services.report_file_service import ReportFileService
from app.api.deps.report_file_deps import get_report_file_service

router = APIRouter()


@router.post("/api/docx/generate", response_model=ReportResult)
async def generate_report_endpoint(
    topic: str = Form(..., description="报告主题"),
    language: Optional[str] = Form(default=None, description="输出语言，例如 zh/EN 等"),
    file_uuids: Optional[str] = Form(
        default=None,
        description="已上传文件的UUID列表，用逗号分隔，例如: uuid1,uuid2,uuid3",
    ),
    user_id: str = Form(default="default_user", description="用户ID"),  # TODO: 从认证中获取
    report_file_service: Optional[ReportFileService] = Depends(get_report_file_service),
) -> ReportResult:
    log_session = start_execution_log(
        flow_type="report_generation",
        metadata={"topic": topic, "language": language},
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received /api/docx/generate request",
        {"topic_preview": topic[:120], "language": language},
    )
    try:
        t0 = time.perf_counter()
        if not topic.strip():
            raise HTTPException(status_code=400, detail="topic 不能为空")

        parsed_content = ""
        reference_sources: list[str] = []

        if file_uuids:
            try:
                uuid_list = [u.strip() for u in file_uuids.split(",") if u.strip()]
                if len(uuid_list) > 5:
                    raise HTTPException(status_code=400, detail="最多支持引用5个文件")
                if uuid_list:
                    parsed_content = await get_file_contents_by_uuids(uuid_list)
                    for uuid_str in uuid_list:
                        file_info = file_upload_service.get_file_info_by_uuid(uuid_str.strip())
                        reference_sources.append(
                            file_info.original_name if file_info else f"UUID文件{uuid_str}"
                        )
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
            log_execution_event("document_upload", "No file references provided", {})

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

        # 尝试上传到对象存储
        file_uuid = None
        preview_url = None
        download_url = None
        storage_enabled = False

        if report_file_service:
            try:
                t_upload = time.perf_counter()
                log_execution_event("storage_upload", "Uploading report to object storage", {})

                filepath = result.get("filepath")
                if filepath and Path(filepath).exists():
                    # 上传文件到对象存储
                    file_uuid = await report_file_service.upload_report_file(
                        file_path=Path(filepath),
                        original_filename=Path(filepath).name,
                        user_id=user_id,
                        expire_days=30
                    )

                    # 生成预览和下载URL路径（相对路径）
                    preview_url = f"/api/reports/{file_uuid}/preview"
                    download_url = f"/api/reports/{file_uuid}/download"
                    storage_enabled = True

                    log_execution_event(
                        "storage_upload",
                        "Report uploaded to object storage successfully",
                        {
                            "file_uuid": file_uuid,
                            "preview_url": preview_url,
                            "upload_duration_sec": round(time.perf_counter() - t_upload, 3),
                        },
                    )
                    logger.info(f"Report uploaded to storage: uuid={file_uuid}, preview_url={preview_url}")
                else:
                    logger.warning(f"Report file not found at {filepath}, skipping storage upload")

            except Exception as storage_error:
                # 对象存储上传失败不影响报告生成结果
                logger.error(f"Failed to upload report to object storage: {storage_error}")
                log_execution_event(
                    "storage_upload",
                    "Failed to upload report to object storage",
                    {"error": str(storage_error)},
                )

        end_execution_log(
            status="completed",
            details={
                "filepath": result.get("filepath"),
                "file_uuid": file_uuid,
                "storage_enabled": storage_enabled,
                "total_duration_sec": round(time.perf_counter() - t0, 3),
            },
        )
        log_closed = True

        # 返回扩展的结果
        return ReportResult(
            **result,
            file_uuid=file_uuid,
            preview_url=preview_url,
            download_url=download_url,
            storage_enabled=storage_enabled,
        )
    except HTTPException as exc:
        log_execution_event("error", "HTTP error during /api/docx/generate", {"status_code": exc.status_code, "detail": exc.detail})
        end_execution_log(status="failed", details={"status_code": exc.status_code, "detail": exc.detail})
        log_closed = True
        raise
    except Exception as exc:
        log_execution_event("error", "Unexpected failure during /api/docx/generate", {"error": str(exc)})
        end_execution_log(status="failed", details={"error": str(exc)})
        log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()
