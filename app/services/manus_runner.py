import asyncio
from typing import Optional

from app.agent.manus import Manus
from app.logger import logger


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
    agent = await Manus.create()
    try:
        final_prompt = (prompt or "").strip()
        if not final_prompt and allow_interactive_fallback:
            final_prompt = input("Enter your prompt: ").strip()

        if not final_prompt:
            logger.warning("Empty prompt provided.")
            return None

        logger.warning("Processing your request...")
        result = await agent.run(final_prompt)
        logger.info("Request processing completed.")
        return result
    except KeyboardInterrupt:
        logger.warning("Operation interrupted.")
        return None
    finally:
        await agent.cleanup()


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
