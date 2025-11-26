import argparse
import asyncio
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.logger import logger
from app.services import (create_structured_document_task,
                          get_structured_document_task, run_manus_flow)
from app.services.document_parser_service import DocumentParserService
from app.services.document_summary_service import DocumentSummaryService
from app.services.execution_log_service import (attach_execution_log,
                                                end_execution_log,
                                                log_execution_event,
                                                start_execution_log)

app = FastAPI(title="OpenManus Service", version="1.0.0")
_service_lock: Optional[asyncio.Lock] = None


class RunRequest(BaseModel):
    prompt: str = Field(..., description="任务提示内容")
    allow_interactive_fallback: bool = Field(
        default=False, description="是否在缺少 prompt 时回退到交互输入（HTTP 接口默认关闭）"
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


@app.on_event("startup")
async def initialize_lock():
    global _service_lock
    _service_lock = asyncio.Lock()
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
            {"result_length": len(result or ""), "result_preview": (result or "")[:200]},
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


@app.post("/documents/structured", response_model=DocumentResponse)
async def structured_document_endpoint(
    topic: str = Form(..., description="文档主题或题目"),
    filepath: Optional[str] = Form(default=None, description="可选的存储路径（默认存到 workspace 下）"),
    language: Optional[str] = Form(default=None, description="输出语言，默认从配置 document.default_language 读取"),
    upload_files: List[UploadFile] = File(default=[], description="上传的文件，最多3个文件")
) -> DocumentResponse:
    topic = topic.strip()

    log_session = start_execution_log(
        flow_type="structured_document",
        metadata={
            "topic": topic,
            "filepath": filepath,
            "language": language,
        },
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received structured document request",
        {
            "has_uploads": bool(upload_files),
            "upload_count": len(upload_files),
            "language": language,
            "filepath": filepath,
        },
    )

    if not topic:
        log_execution_event(
            "error",
            "Topic missing",
            {},
        )
        end_execution_log(status="failed", details={"error": "Topic must not be empty."})
        log_closed = True
        raise HTTPException(status_code=400, detail="Topic must not be empty.")

    try:
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

        # 处理上传的文件并解析内容
        parser_service = DocumentParserService()
        summary_service = DocumentSummaryService()
        parsed_content = ""
        summary_text = ""
        reference_sources: list[str] = []

        if upload_files:
            reference_sources = [
                file.filename or f"上传文件{idx + 1}"
                for idx, file in enumerate(upload_files)
            ]
            try:
                parsed_content = await parser_service.parse_uploaded_files(upload_files)
                logger.info(f"成功解析 {len(upload_files)} 个上传文件")
                log_execution_event(
                    "document_upload",
                    "Uploaded files parsed",
                    {
                        "file_count": len(upload_files),
                        "filenames": [file.filename for file in upload_files],
                        "parsed_length": len(parsed_content),
                    },
                )
            except Exception as e:
                logger.error(f"文件解析失败: {e}")
                log_execution_event(
                    "error",
                    "File parsing failed",
                    {"error": str(e)},
                )
                end_execution_log(status="failed", details={"error": str(e)})
                log_closed = True
                raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")

            if parsed_content.strip():
                try:
                    summary_text = await summary_service.summarize(
                        parsed_content, language=language
                    )
                    logger.info("上传文件摘要生成成功")
                    log_execution_event(
                        "document_upload",
                        "Summary generated",
                        {"summary_length": len(summary_text)},
                    )
                except Exception as e:
                    logger.error(f"文件摘要生成失败: {e}")
                    log_execution_event(
                        "error",
                        "Summary generation failed",
                        {"error": str(e)},
                    )
                    end_execution_log(status="failed", details={"error": str(e)})
                    log_closed = True
                    raise HTTPException(status_code=500, detail="文件摘要生成失败，请稍后重试")

        enhanced_topic = topic
        if summary_text.strip():
            enhanced_topic = (
                f"{topic}\n\n以下是根据上传文件提炼的摘要，请结合这些要点生成文档：\n{summary_text}"
            )

        doc_info = await create_structured_document_task(
            topic=enhanced_topic,
            filepath=filepath,
            language=language,
            reference_content=parsed_content,
            reference_sources=reference_sources,
            execution_log_id=log_session.session_id,
        )
        log_execution_event(
            "workflow",
            "Structured document task created",
            {"task_id": doc_info.get("task_id"), "sections": len(doc_info.get("sections", []))},
        )

        return DocumentResponse(**doc_info)

    except HTTPException as exc:
        if not log_closed:
            log_execution_event(
                "error",
                "HTTP error during structured document request",
                {"status_code": exc.status_code, "detail": exc.detail},
            )
            end_execution_log(
                status="failed",
                details={"status_code": exc.status_code, "detail": exc.detail},
            )
            log_closed = True
        raise
    except Exception as exc:
        if not log_closed:
            log_execution_event(
                "error",
                "Unexpected failure during structured document request",
                {"error": str(exc)},
            )
            end_execution_log(status="failed", details={"error": str(exc)})
            log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()


@app.get("/documents/structured/{task_id}", response_model=DocumentResponse)
async def structured_document_status(task_id: str) -> DocumentResponse:
    if _service_lock is None:
        raise HTTPException(
            status_code=503, detail="Service is initializing, please retry."
        )

    try:
        doc_info = await get_structured_document_task(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")

    session = None
    log_id = doc_info.get("execution_log_id")
    if log_id:
        session = attach_execution_log(log_id)
        if session:
            log_execution_event(
                "http_request",
                "Structured document status queried",
                {"task_id": task_id, "status": doc_info.get("status")},
            )

    try:
        return DocumentResponse(**doc_info)
    finally:
        if session:
            session.deactivate()


@app.get("/documents/supported-formats")
async def get_supported_formats():
    """获取支持的文件格式信息"""
    parser_service = DocumentParserService()
    return parser_service.get_supported_formats()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Manus once via CLI or start the HTTP service."
    )
    parser.add_argument("--prompt", type=str, help="Run once with the given prompt.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host.")
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
