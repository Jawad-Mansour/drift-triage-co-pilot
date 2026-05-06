from typing import Literal

from langgraph.graph import END
from langgraph.types import Command

from backend.agent.agents.state import AgentState
from backend.agent.core.logging import get_logger

log = get_logger(__name__)

_VALID = {"triage", "action", "comms"}
MAX_STEPS = 10


def supervisor_node(
    state: AgentState,
) -> Command[Literal["triage", "action", "comms", "__end__"]]:
    """Pure router — reads next_node set by each worker node.

    No LLM. Each node writes its own next_node into state; the supervisor
    just follows that instruction. MAX_STEPS guards against runaway loops.
    """
    step_count = state.get("step_count", 0) + 1  # type: ignore[misc]

    if step_count > MAX_STEPS:
        log.warning("supervisor_max_steps", step_count=step_count)
        return Command(goto=END, update={"step_count": step_count})

    next_node = state.get("next_node")

    if not next_node or next_node not in _VALID:
        log.info("supervisor_ending", next_node=next_node, step_count=step_count)
        return Command(goto=END, update={"step_count": step_count})

    log.info("supervisor_routing", next_node=next_node, step_count=step_count)
    return Command(goto=next_node, update={"step_count": step_count})
