from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Form, HTTPException

from app.logger import logger
from app.schemas.thinkchain import (
    ThinkchainGenerateResponse,
    ThinkchainOverviewResponse,
)
from app.services.file_upload_service import (
    file_upload_service,
    get_file_contents_by_uuids,
)
from app.services.thinkchain_normalizer import normalize_step_result
from app.services.thinkchain_registry import thinkchain_registry
from app.services.thinkchain_state_engine import thinkchain_state_engine
from app.services.thinkchain_log_service import thinkchain_log_service
from app.services.thinkchain_analysis_service import thinkchain_analysis_service
from app.services.thinkchain_post_action_service import thinkchain_post_action_service
from app.schemas.thinkchain_analysis import (
    ThinkchainAnalysisRequest,
    ThinkchainAnalysisResponse,
)

router = APIRouter()


def _validate_task_type(task_type: Optional[str]) -> str:
    t = (task_type or "normal").lower()
    # accept 'pptx' as alias of 'ppt'
    if t == "pptx":
        t = "ppt"
    if t not in {"normal", "report", "ppt"}:
        raise HTTPException(
            status_code=400, detail="非法 task_type，允许: normal/report/ppt"
        )
    return t


@router.post("/api/thinkchain/overview", response_model=ThinkchainOverviewResponse)
async def thinkchain_overview_endpoint(
    topic: str = Form(..., description="任务主题"),
    task_type: Optional[str] = Form(
        default="normal", description="任务类型：normal/report/ppt"
    ),
    language: Optional[str] = Form(default="zh", description="输出语言，例如 zh/en"),
    file_uuids: Optional[List[str]] = Form(
        default=None, description="文件UUID数组，如 ['uuid1','uuid2']"
    ),
    step_count: Optional[int] = Form(
        default=None, description="步骤数量（8-12，不传则随机）"
    ),
):
    if not topic or not topic.strip():
        raise HTTPException(status_code=400, detail="topic 不能为空")

    ttype = _validate_task_type(task_type)
    reference_sources: List[str] = []
    valid_uuid_files: List[str] = []

    if file_uuids:
        try:
            uuid_list = [u.strip() for u in file_uuids if u and str(u).strip()]
            if len(uuid_list) > 5:
                raise HTTPException(status_code=400, detail="最多支持引用5个文件")
            # Only verify existence and collect names; do not parse contents here
            for uuid_str in uuid_list:
                file_info = file_upload_service.get_file_info_by_uuid(uuid_str)
                if file_info:
                    reference_sources.append(file_info.original_name)
                    valid_uuid_files.append(uuid_str)
        except Exception as e:
            logger.warning(f"UUID文件检查失败，将继续不带文件生成: {str(e)}")
            reference_sources = []
            valid_uuid_files = []

    # Generate steps with fixed pre-steps (titles fixed, descriptions via LLM) + flexible LLM steps
    try:
        import random

        from app.services.thinkchain_overview_service import thinkchain_overview_service

        # Use LLM-based intent detection and pre-step description generation
        pre_steps, fixed_titles, optimized_topic = (
            await thinkchain_overview_service.generate_pre_steps(
                topic=topic.strip(),
                language=language or "zh",
                has_files=bool(valid_uuid_files),
                query_text=topic.strip(),
            )
        )

        # Determine total and generated counts
        desired_total = int(step_count) if step_count else random.randint(8, 12)
        desired_total = max(8, min(12, desired_total))
        gen_count = max(0, desired_total - len(pre_steps))

        steps_raw = await thinkchain_overview_service.generate_steps(
            topic=topic.strip(),
            language=language or "zh",
            count=gen_count,
            reserved_titles=fixed_titles,
        )
        # Normalize and merge, then renumber keys starting from 1
        normalized_steps: List[Dict[str, Any]] = []
        merged = pre_steps + [
            {
                "key": int(s.get("key", i)),
                "title": str(s.get("title", f"步骤{i}")),
                "description": str(s.get("description", "")),
            }
            for i, s in enumerate(steps_raw, start=1)
            if isinstance(s, dict)
        ]
        for idx, s in enumerate(merged, start=1):
            normalized_steps.append(
                {"key": idx, "title": s["title"], "description": s["description"]}
            )

        chain_id = await thinkchain_registry.create_chain(
            topic=(optimized_topic.strip() if isinstance(optimized_topic, str) and optimized_topic.strip() else topic.strip()),
            task_type=ttype,
            language=language or "zh",
            steps=normalized_steps,
            reference_sources=reference_sources,
            reference_file_uuids=valid_uuid_files,
        )

        return {
            "status": "success",
            "chain_id": chain_id,
            "task_type": ttype,
            "topic": optimized_topic.strip() or topic.strip(),
            "language": language or "zh",
            "reference_sources": reference_sources,
            "uuid_files": valid_uuid_files,
            "chain": {"steps": normalized_steps},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Thinkchain overview error: {e}")
        raise HTTPException(status_code=500, detail=f"生成任务链失败: {str(e)}")


@router.post("/api/thinkchain/generate", response_model=ThinkchainGenerateResponse)
async def thinkchain_generate_endpoint(
    chain_id: str = Form(..., description="概览链ID"),
    session_id: Optional[str] = Form(default=None, description="执行会话ID"),
):
    # 通过 chain_id 获取链信息
    rec = await thinkchain_registry.get_chain(chain_id)
    if not rec:
        raise HTTPException(status_code=400, detail="无效的 chain_id")

    # 从链记录中获取所有必需参数
    steps = rec.steps
    resolved_topic = rec.topic
    resolved_language = rec.language
    reference_sources = rec.reference_sources
    ttype = rec.task_type

    # 文件内容处理现在由状态引擎根据步骤标题来判断
    # 当步骤标题为"[PRE] 文件审阅与要点整合"时，会自动处理文件摘要
    reference_content = ""

    if not steps:
        raise HTTPException(status_code=400, detail="步骤链为空")

    # Execute one or multiple steps
    import time as _time

    started = _time.time()
    try:
        step_result, is_completed, new_session_id = (
            await thinkchain_state_engine.process_request(
                topic=resolved_topic or "",
                task_type=ttype,
                language=resolved_language,
                steps=steps,  # driving by overview chain
                session_id=session_id,
                reference_content=reference_content,
                reference_sources=reference_sources,
                reference_file_uuids=rec.reference_file_uuids,
            )
        )

        normalized_item = normalize_step_result(
            step_result, topic=resolved_topic or "", language=resolved_language
        )

        # Logging to workspace/thinkchain_logs as JSONL
        try:
            # Start record on first round (no incoming session_id)
            if session_id is None:
                thinkchain_log_service.log_session_start(
                    chain_id=chain_id,
                    session_id=new_session_id,
                    metadata={
                        "topic": resolved_topic or "",
                        "task_type": ttype,
                        "language": resolved_language,
                        "steps_count": len(steps),
                        "reference_sources": reference_sources,
                        "reference_file_uuids": rec.reference_file_uuids,
                    },
                )
            # Append step record
            thinkchain_log_service.log_step(
                chain_id=chain_id,
                session_id=new_session_id,
                step_result=step_result,
                normalized=normalized_item,
            )
            # End record when completed
            if is_completed:
                thinkchain_log_service.log_session_end(
                    chain_id=chain_id,
                    session_id=new_session_id,
                    status="completed",
                    details={
                        "topic": resolved_topic or "",
                        "final_normalized": normalized_item,
                    },
                )
        except Exception:
            # Logging failures must not break API flow
            pass

        resp = {
            "status": "success",
            "outline": [normalized_item],
            "session_id": new_session_id,
            "is_completed": is_completed,
            "topic": resolved_topic or "",
            "language": resolved_language,
            "execution_time": _time.time() - started,
            "reference_sources": reference_sources,
        }

        # Post-completion tasks: analysis + optional report/ppt generation
        if is_completed:
            try:
                # fire-and-forget background analysis (not to block response)
                import asyncio

                async def _post_tasks():
                    # generate analysis and log an event
                    analysis = await thinkchain_analysis_service.generate_analysis(
                        chain_id=chain_id, session_id=new_session_id, language=resolved_language
                    )
                    try:
                        thinkchain_log_service.log_event(
                            chain_id=chain_id,
                            session_id=new_session_id,
                            event="analysis_generated",
                            data={"analysis_path": analysis.get("log_path", "")},
                        )
                    except Exception:
                        pass
                    # run optional post actions (report/ppt)
                    try:
                        await thinkchain_post_action_service.run_post_actions(
                            task_type=ttype,
                            chain_id=chain_id,
                            session_id=new_session_id,
                            topic=resolved_topic or "",
                            language=resolved_language,
                            reference_file_uuids=rec.reference_file_uuids,
                        )
                    except Exception:
                        pass

                asyncio.create_task(_post_tasks())

                # Allow clients to pull analysis via the new endpoint
                resp["analysis_ready"] = True
                resp["analysis_endpoint"] = f"/api/thinkchain/analysis?chain_id={chain_id}"
            except Exception:
                resp["analysis_ready"] = False

            # Expose prepared digest UUID for clients, even as background tasks run
            try:
                digest_uuid = thinkchain_analysis_service.create_digest_upload_file(
                    chain_id=chain_id, session_id=new_session_id
                )
                resp["post_actions"] = {
                    "log_digest_uuid": digest_uuid,
                    "hints": {
                        "report": {
                            "endpoint": "/api/docx/generate",
                            "params": {
                                "topic": resolved_topic or "",
                                "language": resolved_language,
                                "file_uuids": digest_uuid,
                            },
                        },
                        "ppt": {
                            "endpoint": "/api/ppt-outline/generate",
                            "params": {
                                "topic": resolved_topic or "",
                                "language": resolved_language,
                                "file_uuids": digest_uuid,
                            },
                        },
                    },
                }
            except Exception:
                pass

        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Thinkchain generate error: {e}")
        # Try to log session failure if we have identifiers
        try:
            if chain_id and session_id:
                thinkchain_log_service.log_session_end(
                    chain_id=chain_id,
                    session_id=session_id,
                    status="failed",
                    details={"error": str(e)},
                )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")
