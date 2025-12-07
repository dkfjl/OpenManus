import asyncio
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.schemas.run import RunRequest, RunResponse
from app.logger import logger
from app.services import run_manus_flow
from app.services.execution_log_service import (
    end_execution_log,
    log_execution_event,
    start_execution_log,
)
from app.services.prompt_service import PromptService

router = APIRouter()


@router.post("/run", response_model=RunResponse)
async def run_manus_endpoint(payload: RunRequest, request: Request) -> RunResponse:
    # 初始化 prompt service
    prompt_service = PromptService()

    # 处理提示词：支持 promptId 注入和变量替换
    final_prompt = payload.prompt or ""

    if payload.promptId:
        try:
            # 获取当前用户ID（用于个人提示词）
            owner_id = os.getenv("CURRENT_USER_ID", "default_user")

            # 使用 service 的 get_and_merge_prompt 方法
            template_prompt = prompt_service.get_and_merge_prompt(
                prompt_type=payload.promptType,
                prompt_id=payload.promptId,
                owner_id=owner_id if payload.promptType == "personal" else None,
                merge_vars=payload.mergeVars,
                additional_prompt=final_prompt if final_prompt else None
            )

            # 如果没有 additional_prompt，直接使用模板
            final_prompt = template_prompt

            logger.info(f"Using prompt template {payload.promptId}, final prompt length: {len(final_prompt)}")
        except Exception as e:
            logger.error(f"Failed to load prompt template {payload.promptId}: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to load prompt template: {str(e)}"
            )

    prompt = final_prompt.strip()
    log_session = start_execution_log(
        flow_type="manus_flow",
        metadata={
            "entrypoint": "http.run",
            "allow_interactive_fallback": payload.allow_interactive_fallback,
            "prompt_id": payload.promptId,
            "prompt_type": payload.promptType,
            "has_merge_vars": payload.mergeVars is not None,
        },
    )
    log_closed = False
    log_execution_event(
        "http_request",
        "Received /run invocation",
        {"prompt_preview": prompt[:200], "prompt_length": len(prompt)},
    )

    if not prompt:
        log_execution_event("error", "Prompt missing for /run", {})
        end_execution_log(status="failed", details={"error": "Prompt must not be empty."})
        log_closed = True
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    # Service lock lives on app.state
    service_lock: Optional[asyncio.Lock] = getattr(request.app.state, "service_lock", None)
    if service_lock is None:
        log_execution_event("error", "Service lock missing", {"detail": "Service initializing"})
        end_execution_log(status="failed", details={"error": "Service initializing"})
        log_closed = True
        raise HTTPException(status_code=503, detail="Service is initializing, please retry.")

    if service_lock.locked():
        log_execution_event("error", "Service busy", {})
        end_execution_log(status="failed", details={"error": "Agent busy"})
        log_closed = True
        raise HTTPException(status_code=409, detail="Agent is already processing another request.")

    try:
        async with service_lock:
            result = await run_manus_flow(
                prompt=prompt, allow_interactive_fallback=payload.allow_interactive_fallback
            )
        log_execution_event(
            "workflow",
            "run_manus_flow completed",
            {"result_length": len(result or ""), "result_preview": (result or "")[:200]},
        )
        end_execution_log(status="completed", details={"result_length": len(result or "")})
        log_closed = True
        return RunResponse(status="completed", result=result)
    except HTTPException as exc:
        log_execution_event("error", "HTTP error during /run", {"status_code": exc.status_code, "detail": exc.detail})
        end_execution_log(status="failed", details={"status_code": exc.status_code, "detail": exc.detail})
        log_closed = True
        raise
    except Exception as exc:
        log_execution_event("error", "Unexpected failure during /run", {"error": str(exc)})
        end_execution_log(status="failed", details={"error": str(exc)})
        log_closed = True
        raise
    finally:
        if not log_closed:
            log_session.deactivate()
