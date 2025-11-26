import asyncio
from typing import Optional

from app.agent.manus import Manus
from app.logger import logger
from app.services.execution_log_service import (
    current_execution_log_id,
    end_execution_log,
    log_execution_event,
    start_execution_log,
)


async def run_manus_flow(
    prompt: Optional[str] = None,
    *,
    allow_interactive_fallback: bool = True,
) -> Optional[str]:
    """
    Execute the standard Manus workflow.

    Args:
        prompt: Optional initial user prompt. If omitted and allow_interactive_fallback
            is True, an interactive input() prompt is shown (CLI-style behavior).
        allow_interactive_fallback: When False, the function will not ask for input and
            instead returns None if prompt is empty.

    Returns:
        Result string returned by Manus.run(), or None if execution was skipped.
    """
    existing_log_id = current_execution_log_id()
    log_session = None
    log_closed = False
    if not existing_log_id:
        log_session = start_execution_log(
            flow_type="manus_flow",
            metadata={"entrypoint": "service.run_manus_flow"},
        )
    log_execution_event(
        "workflow",
        "Initializing Manus agent",
        {"has_prompt": bool(prompt), "allow_interactive_fallback": allow_interactive_fallback},
    )

    agent = await Manus.create()
    try:
        final_prompt = (prompt or "").strip()
        if not final_prompt and allow_interactive_fallback:
            final_prompt = input("Enter your prompt: ").strip()

        if not final_prompt:
            logger.warning("Empty prompt provided.")
            log_execution_event(
                "workflow",
                "Prompt missing, aborting run_manus_flow",
                {},
            )
            return None

        logger.warning("Processing your request...")
        log_execution_event(
            "workflow",
            "Starting Manus agent run",
            {"prompt_preview": final_prompt[:200]},
        )
        result = await agent.run(final_prompt)
        logger.info("Request processing completed.")
        log_execution_event(
            "workflow",
            "Manus agent run completed",
            {"result_length": len(result or "")},
        )
        if log_session:
            end_execution_log(
                status="completed",
                details={"result_length": len(result or "")},
            )
            log_closed = True
        return result
    except KeyboardInterrupt:
        logger.warning("Operation interrupted.")
        log_execution_event("workflow", "run_manus_flow interrupted", {})
        if log_session and not log_closed:
            end_execution_log(status="cancelled", details={"reason": "KeyboardInterrupt"})
            log_closed = True
        return None
    except Exception as exc:
        log_execution_event(
            "error",
            "run_manus_flow failed",
            {"error": str(exc)},
        )
        if log_session and not log_closed:
            end_execution_log(status="failed", details={"error": str(exc)})
            log_closed = True
        raise
    finally:
        await agent.cleanup()
        if log_session and not log_closed:
            log_session.deactivate()


def run_manus_flow_sync(
    prompt: Optional[str] = None,
    *,
    allow_interactive_fallback: bool = True,
) -> Optional[str]:
    """
    Synchronous helper that wraps run_manus_flow inside asyncio.run().
    """
    return asyncio.run(
        run_manus_flow(
            prompt=prompt,
            allow_interactive_fallback=allow_interactive_fallback,
        )
    )
