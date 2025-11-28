import argparse
import asyncio
import json
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
from app.services.md_slide_generation_service import \
    generate_marp_markdown_from_steps
from app.services.pptx_report_generation_service import \
    generate_pptx_report_from_steps
from app.services.report_generation_service import generate_report_from_steps
from app.services.thinking_steps_service import generate_thinking_steps

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


class PPTLayoutPlaceholder(BaseModel):
    idx: Optional[int]
    type: Optional[str]
    name: Optional[str]


class PPTLayoutInfo(BaseModel):
    index: int
    name: str
    placeholders: list[PPTLayoutPlaceholder]


class PPTInspectResponse(BaseModel):
    status: str
    layouts: list[PPTLayoutInfo]


class PPTGenerateResponse(BaseModel):
    status: str
    filepath: str
    slides_written: int


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

@app.post("/thinking/steps")
async def thinking_steps_endpoint(payload: ThinkingStepsRequest):
    """生成思考过程步骤数组（15-20步）。

    请求体字段：
    - goal: 可选，任务目标/主题，用于个性化描述
    - count: 可选，期望的步骤数量（自动裁剪到15-20）
    - format: 可选，输出格式（json/md，默认json）

    返回：
    - json格式：直接返回一个由 JSON 对象组成的数组，每个对象包含：
      - key: 顺序号（从1开始）
      - title: 执行动作标题
      - description: 对该动作的中文描述
      - showDetail: 是否展示细节（true/false）
      - detailType: 当 showDetail 为 true 时出现，取值如 image/table/list/code/diagram
    - md格式：返回 Markdown 格式的思考步骤文档
    """
    log_session = start_execution_log(
        flow_type="thinking_steps",
        metadata={"goal": payload.goal, "count": payload.count},
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received /thinking/steps request",
        {"goal_preview": (payload.goal or "")[:120], "count": payload.count},
    )
    try:
        steps = await generate_thinking_steps(payload.goal, payload.count or 20, payload.format or "json")
        log_execution_event(
            "workflow",
            "Thinking steps generated",
            {"steps": len(steps), "format": payload.format or "json"},
        )
        end_execution_log(status="completed", details={"steps": len(steps)})
        log_closed = True
        return steps
    except Exception as exc:
        log_execution_event(
            "error",
            "Unexpected failure during /thinking/steps",
            {"error": str(exc)},
        )
        end_execution_log(status="failed", details={"error": str(exc)})
        log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()


@app.post("/generating/report", response_model=ReportResult)
async def generate_report_endpoint(
    topic: str = Form(..., description="报告主题"),
    format: str = Form("docx", description="输出格式，支持 docx 或 pptx"),
    language: Optional[str] = Form(default=None, description="输出语言，例如 zh/EN 等"),
    filepath: Optional[str] = Form(default=None, description="保存路径（相对workspace）"),
    style: Optional[str] = Form(default=None, description="PPT风格（通用/学术风/职场风/教育风/营销风）"),
    model: Optional[str] = Form(default=None, description="AI模型（例如 gemini-3-pro-preview）"),
    upload_files: List[UploadFile] = File(default=[], description="参考资料上传文件，最多3个文件"),
) -> ReportResult:
    log_session = start_execution_log(
        flow_type="report_generation",
        metadata={
            "topic": topic,
            "format": format,
            "language": language,
        },
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received /generating/report request",
        {
            "topic_preview": topic[:120],
            "format": format,
            "language": language,
        },
    )
    try:
        if not topic.strip():
            raise HTTPException(status_code=400, detail="topic 不能为空")

        # Parse uploaded files (optional)
        parser_service = DocumentParserService()
        summary_service = DocumentSummaryService()
        parsed_content = ""
        reference_sources: list[str] = []
        if upload_files:
            reference_sources = [
                file.filename or f"上传文件{idx + 1}"
                for idx, file in enumerate(upload_files)
            ]
            try:
                parsed_content = await parser_service.parse_uploaded_files(upload_files)
                log_execution_event(
                    "document_upload",
                    "Uploaded files parsed (report)",
                    {
                        "file_count": len(upload_files),
                        "filenames": [file.filename for file in upload_files],
                        "parsed_length": len(parsed_content),
                    },
                )
            except Exception as e:
                end_execution_log(status="failed", details={"error": str(e)})
                raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")
            # Summarize parsed content for prompt context
            if parsed_content.strip():
                try:
                    summary_text = await summary_service.summarize(parsed_content, language=language)
                    parsed_content = summary_text  # pass summary to agent prompt
                except Exception:
                    pass

        if format.lower() == "pptx":
            # New behavior: generate PPTX locally (no third-party API)
            from app.config import config
            from app.services.aippt_generation_service import \
                generate_pptx_from_aippt
            from app.services.aippt_outline_service import \
                generate_aippt_outline

            # Step 1: Generate PPT outline
            outline_result = await generate_aippt_outline(
                topic=topic.strip(),
                language=language,
                reference_content=parsed_content,
            )

            if outline_result["status"] == "failed":
                raise HTTPException(
                    status_code=500,
                    detail=f"PPT outline generation failed: {outline_result.get('error', 'Unknown error')}"
                )

            # Step 2: Generate PPTX locally using the outline
            result = await generate_pptx_from_aippt(
                topic=topic.strip(),
                outline=outline_result["outline"],
                language=language,
                style=style or config.aippt_config.default_style,
                model=model or config.aippt_config.default_model,
                filepath=filepath,
            )
        else:
            # default to docx path to preserve backward compat
            result = await generate_report_from_steps(
                topic=topic.strip(),
                language=language,
                fmt="docx",
                filepath=filepath,
                reference_content=parsed_content,
                reference_sources=reference_sources,
            )
        log_execution_event(
            "workflow",
            "Report generated",
            {"filepath": result.get("filepath"), "title": result.get("title")},
        )
        end_execution_log(status="completed", details={"filepath": result.get("filepath")})
        log_closed = True
        return ReportResult(**result)
    except HTTPException as exc:
        log_execution_event(
            "error",
            "HTTP error during /generating/report",
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
            "Unexpected failure during /generating/report",
            {"error": str(exc)},
        )
        end_execution_log(status="failed", details={"error": str(exc)})
        log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()


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
