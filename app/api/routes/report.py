import time
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Depends, Request

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
from app.services.knowledge_service import KnowledgeService

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
    request: Request = None,
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

        # 先进行知识库检索，将结果作为“摘要性质”的上下文并入参考内容
        kb_context = ""
        try:
            t_kb = time.perf_counter()
            ks = KnowledgeService()
            kb_items, kb_total, _ = await ks.retrieve(
                query=topic.strip(),
                # 其余参数使用配置默认值
                return_expansion=False,
            )
            if kb_total > 0:
                # 拼接前若干片段，限制体量，避免上下文过长
                max_chars = 3000
                acc = []
                length = 0
                for rec in kb_items:
                    text = (rec.content or "").strip()
                    if not text:
                        continue
                    if length and length + len(text) + 2 > max_chars:
                        break
                    acc.append(text)
                    length += len(text) + 2
                    # 记录来源（尽量取到可读标题/URL/ID）
                    md = rec.metadata or {}
                    src = md.get("title") or md.get("url") or md.get("document_id") or md.get("doc_id")
                    if src:
                        reference_sources.append(str(src))
                kb_context = "\n\n".join(acc)[:max_chars]
            log_execution_event(
                "kb_retrieve",
                "KB retrieval for report context finished",
                {"kb_total": kb_total, "kb_ctx_len": len(kb_context or "")},
            )
        except Exception as e:
            # 检索失败不影响主流程
            log_execution_event("kb_retrieve", "KB retrieval failed, continue without KB", {"error": str(e)})

        # 合并知识库上下文与上传文件解析内容
        if kb_context and parsed_content:
            parsed_content = kb_context + "\n\n" + parsed_content
        elif kb_context:
            parsed_content = kb_context

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
        # 从合并后的参考内容中，尽量拆分出“上传文件摘录”和“知识检索摘录”
        file_excerpt = None
        kb_excerpt = None
        if parsed_content and kb_context:
            # parsed_content 此时可能包含 kb_context + 上传文件内容，做一次简单拆分
            # 这里以 kb_context 的文本作为分隔标记（若失败则降级为整体摘要）
            try:
                if parsed_content.startswith(kb_context):
                    kb_excerpt = kb_context
                    file_excerpt = parsed_content[len(kb_context):].strip() or None
                else:
                    # 找不到稳定分隔，则不做区分
                    kb_excerpt = kb_context
            except Exception:
                kb_excerpt = kb_context
        elif kb_context:
            kb_excerpt = kb_context
        else:
            file_excerpt = parsed_content

        result = await generate_report_from_steps(
            topic=topic.strip(),
            language=language,
            fmt="docx",
            reference_content=parsed_content,
            reference_sources=reference_sources,
            file_reference_excerpt=file_excerpt,
            kb_reference_excerpt=kb_excerpt,
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

        # 尝试上传到对象存储，并直接返回可访问的预签名直链
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
                        expire_days=30,
                    )

                    # 直接生成预签名直链（用于预览/下载）
                    try:
                        access_ip = (
                            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                            or (request.client.host if request and request.client else None)
                        ) if request else None
                        user_agent = request.headers.get("User-Agent") if request else None

                        preview_url = await report_file_service.get_preview_url(
                            file_uuid=file_uuid,
                            user_id=user_id,
                            access_ip=access_ip,
                            user_agent=user_agent,
                        )
                        download_url = await report_file_service.get_download_url(
                            file_uuid=file_uuid,
                            user_id=user_id,
                            access_ip=access_ip,
                            user_agent=user_agent,
                        )
                        storage_enabled = True
                    except Exception as gen_url_err:
                        # URL 生成失败不阻塞流程
                        log_execution_event(
                            "storage_upload",
                            "Presigned URL generation failed",
                            {"error": str(gen_url_err)},
                        )

                    log_execution_event(
                        "storage_upload",
                        "Report uploaded to object storage successfully",
                        {
                            "file_uuid": file_uuid,
                            "has_preview_url": bool(preview_url),
                            "has_download_url": bool(download_url),
                            "upload_duration_sec": round(time.perf_counter() - t_upload, 3),
                        },
                    )
                    logger.info(
                        f"Report uploaded to storage: uuid={file_uuid}, has_preview={bool(preview_url)}, has_download={bool(download_url)}"
                    )
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
