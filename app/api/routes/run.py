import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import RunRequest, RunResponse
from app.logger import logger
from app.services import run_manus_flow
from app.services.execution_log_service import (
    end_execution_log,
    log_execution_event,
    start_execution_log,
)

router = APIRouter()


@router.post("/run", response_model=RunResponse)
async def run_manus_endpoint(payload: RunRequest, request: Request) -> RunResponse:
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

