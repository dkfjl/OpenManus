from typing import List, Optional

from app.agent.thinking_steps import ThinkingStepsAgent
from app.services.execution_log_service import log_execution_event


async def generate_thinking_steps(goal: Optional[str], count: int, format: str = "json"):
    """Use an agent to generate a structured thinking steps array.

    Ensures the count is within [15, 20]. Returns formatted output based on format parameter.
    """
    agent = ThinkingStepsAgent(goal=goal, count=count, format=format)
    log_execution_event(
        "workflow",
        "ThinkingStepsAgent initialized",
        {"goal_preview": (goal or "")[:120], "count": count, "format": format},
    )
    await agent.run()
    log_execution_event(
        "workflow",
        "ThinkingStepsAgent finished",
        {"generated": len(agent.steps)},
    )
    return agent.get_formatted_output()
