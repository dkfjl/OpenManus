import argparse
import asyncio
import json
import time
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
        t0 = time.perf_counter()
        if not topic.strip():
            raise HTTPException(status_code=400, detail="topic 不能为空")

        # Parse uploaded files (optional)
        parser_service = DocumentParserService()
        summary_service = DocumentSummaryService()
        parsed_content = ""
        reference_sources: list[str] = []

        def _escape_for_prompt(text: str) -> str:
            # Lightweight escaping to neutralize common prompt/control tokens
            if not text:
                return ""
            t = text.replace("```", "`\u200b``").replace("<|", "＜|").replace("|>", "|＞")
            return t

        def _truncate(v: str, n: int = 200) -> str:
            return v if not v or len(v) <= n else v[:n]

        if upload_files:
            reference_sources = [
                file.filename or f"上传文件{idx + 1}"
                for idx, file in enumerate(upload_files)
            ]
            # Per-file parsing and ≤1000字摘要
            log_execution_event(
                "document_upload",
                "Start processing uploaded files",
                {
                    "file_count": len(upload_files),
                    "filenames": [file.filename for file in upload_files],
                },
            )
            per_file_summaries: list[str] = []
            try:
                t_up0 = time.perf_counter()
                for file in upload_files:
                    # Parse each file independently to enable per-file summaries
                    log_execution_event(
                        "document_upload",
                        "Begin processing single file",
                        {"filename": file.filename},
                    )
                    single_parsed = await parser_service.parse_uploaded_files([file])
                    log_execution_event(
                        "document_upload",
                        "Single file parsed (report)",
                        {
                            "filename": file.filename,
                            "parsed_length": len(single_parsed or ""),
                            "parsed_preview": _truncate(single_parsed or "", 180),
                        },
                    )

                    # Escape and summarize with strict 1000-char cap
                    pre_len = len(single_parsed or "")
                    escaped = _escape_for_prompt(single_parsed)
                    post_len = len(escaped)
                    log_execution_event(
                        "document_upload",
                        "Escaping completed",
                        {
                            "filename": file.filename,
                            "before_length": pre_len,
                            "after_length": post_len,
                        },
                    )
                    block = f"```\n{escaped}\n```"
                    try:
                        log_execution_event(
                            "upload_summary",
                            "LLM summarization start",
                            {
                                "filename": file.filename,
                                "cap_chars": 1000,
                                "input_length": len(block),
                            },
                        )
                        summary_text = await summary_service.summarize_limited(
                            block,
                            language=language or "zh",
                            max_chars=1000,
                        )
                        log_execution_event(
                            "upload_summary",
                            "LLM summarization completed",
                            {
                                "filename": file.filename,
                                "summary_length": len(summary_text or ""),
                                "summary_preview": _truncate(summary_text or "", 180),
                            },
                        )
                    except Exception as _e:
                        # Fallback to trimmed raw content if LLM unavailable
                        summary_text = (escaped or "")[:1000]
                        log_execution_event(
                            "upload_summary",
                            "LLM summarization failed; fallback used",
                            {
                                "filename": file.filename,
                                "error": _truncate(str(_e), 200),
                                "fallback_length": len(summary_text or ""),
                            },
                        )

                    per_file_summaries.append(
                        f"【{file.filename or '未命名文件'}】摘要：\n{summary_text}"
                    )
                    log_execution_event(
                        "upload_summary",
                        "File summary appended",
                        {
                            "filename": file.filename,
                            "current_summary_count": len(per_file_summaries),
                        },
                    )

                parsed_content = "\n\n".join(per_file_summaries).strip()
                log_execution_event(
                    "document_upload",
                    "Per-file summaries prepared",
                    {
                        "file_count": len(upload_files),
                        "filenames": [file.filename for file in upload_files],
                        "summary_total_length": len(parsed_content),
                        "summary_count": len(per_file_summaries),
                        "duration_sec": round(time.perf_counter() - t_up0, 3),
                    },
                )
            except Exception as e:
                end_execution_log(status="failed", details={"error": str(e)})
                raise HTTPException(status_code=400, detail=f"文件解析或摘要失败: {str(e)}")
        else:
            log_execution_event(
                "document_upload",
                "No upload files provided",
                {},
            )

        log_execution_event(
            "report_generation",
            "Format branch selected",
            {
                "format": format.lower(),
                "language": language,
                "style": style,
                "model": model,
                "has_reference": bool(parsed_content.strip()),
                "reference_length": len(parsed_content or ""),
                "reference_sources": len(reference_sources or []),
            },
        )

        if format.lower() == "pptx":
            # New behavior: generate PPTX locally (no third-party API)
            from app.config import config
            from app.services.aippt_generation_service import \
                generate_pptx_from_aippt
            from app.services.aippt_outline_service import \
                generate_aippt_outline
            from app.services.aippt_content_enrichment_service import \
                enrich_aippt_content

            # Step 1: Generate PPT outline
            t_o0 = time.perf_counter()
            outline_result = await generate_aippt_outline(
                topic=topic.strip(),
                language=language,
                reference_content=parsed_content,
            )
            log_execution_event(
                "report_generation",
                "Outline generation finished",
                {
                    "status": outline_result.get("status"),
                    "duration_sec": round(time.perf_counter() - t_o0, 3),
                    "slides": len(outline_result.get("outline") or []),
                },
            )

            if outline_result["status"] == "failed":
                raise HTTPException(
                    status_code=500,
                    detail=f"PPT outline generation failed: {outline_result.get('error', 'Unknown error')}"
                )

            # Step 2: Enrich content (text/case) via dedicated LLM pass
            try:
                t_e0 = time.perf_counter()
                # 2.0: collect web summaries (Bocha→Google) as auxiliary reference
                try:
                    from app.services.web_summary_service import collect_search_summaries
                    web_sum_text, web_sources = await collect_search_summaries(
                        query=topic.strip(), top_k=8
                    )
                except Exception as _ws_e:
                    web_sum_text, web_sources = "", []
                    log_execution_event(
                        "web_summary",
                        "Skipped (error during summary collection)",
                        {"error": str(_ws_e)},
                    )

                # Merge uploaded reference content with web summaries for enrichment
                combined_reference = "\n".join(
                    x for x in [parsed_content or "", web_sum_text or ""] if x.strip()
                )
                enrich_res = await enrich_aippt_content(
                    outline=outline_result["outline"],
                    topic=topic.strip(),
                    language=language or "zh",
                    reference_content=(combined_reference or None),
                )
                log_execution_event(
                    "report_generation",
                    "Text enrichment finished",
                    {
                        "status": enrich_res.get("status"),
                        "updated": enrich_res.get("updated", 0),
                        "duration_sec": round(time.perf_counter() - t_e0, 3),
                        "web_sources": len(web_sources),
                    },
                )
                # Step 2.5: Media enrichment (images & tables) after text enrichment
                from app.services.aippt_media_enrichment_service import (
                    enrich_media_outline,
                )
                text_enriched_outline = (
                    enrich_res.get("outline") or outline_result["outline"]
                )
                t_m0 = time.perf_counter()
                media_res = await enrich_media_outline(
                    outline=text_enriched_outline,
                    topic=topic.strip(),
                    language=language or "zh",
                )
                final_outline = media_res.get("outline") or text_enriched_outline
                log_execution_event(
                    "aippt_enrich",
                    "Outline enrichment finished (text + media)",
                    {
                        "text_status": enrich_res.get("status"),
                        "text_updated": enrich_res.get("updated", 0),
                        "media_images": media_res.get("images_added", 0),
                        "media_tables": media_res.get("tables_added", 0),
                        "media_duration_sec": round(time.perf_counter() - t_m0, 3),
                    },
                )
            except Exception as _e:
                # Preserve text-enriched outline if available; only skip media enrichment
                try:
                    final_outline = text_enriched_outline
                except Exception:
                    final_outline = outline_result["outline"]

            # Step 3: Generate PPTX; use direct_convert to preserve enriched content
            t_g0 = time.perf_counter()
            result = await generate_pptx_from_aippt(
                topic=topic.strip(),
                outline=final_outline,
                language=language,
                style=style or config.aippt_config.default_style,
                model=model or config.aippt_config.default_model,
                filepath=filepath,
                direct_convert=True,
            )
            log_execution_event(
                "report_generation",
                "PPTX generation finished",
                {
                    "status": result.get("status"),
                    "filepath": result.get("filepath"),
                    "duration_sec": round(time.perf_counter() - t_g0, 3),
                },
            )
        else:
            # default to docx path to preserve backward compat
            t_d0 = time.perf_counter()
            log_execution_event(
                "report_generation",
                "DOCX path invoked",
                {
                    "language": language,
                    "filepath": filepath,
                    "reference_length": len(parsed_content or ""),
                    "reference_sources": len(reference_sources or []),
                },
            )
            result = await generate_report_from_steps(
                topic=topic.strip(),
                language=language,
                fmt="docx",
                filepath=filepath,
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
