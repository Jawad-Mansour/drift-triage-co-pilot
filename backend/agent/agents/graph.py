from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agent.agents.nodes.action import action_node
from backend.agent.agents.nodes.comms import comms_node
from backend.agent.agents.nodes.supervisor import supervisor_node
from backend.agent.agents.nodes.triage import triage_node
from backend.agent.agents.state import AgentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Build and compile the drift triage supervisor graph.

    Topology: START → supervisor → triage → supervisor → action → supervisor → comms → END

    The supervisor reads state["next_node"] set by each worker and routes accordingly.
    Checkpointer is required in production for HIL pause/resume — None only in unit tests.
    """
    graph: StateGraph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("triage", triage_node)
    graph.add_node("action", action_node)
    graph.add_node("comms", comms_node)

    # Every run starts at supervisor; supervisor uses Command(goto=...) for all routing
    graph.add_edge(START, "supervisor")
    graph.add_edge("triage", "supervisor")
    graph.add_edge("action", "supervisor")
    graph.add_edge("comms", "supervisor")

    return graph.compile(checkpointer=checkpointer)


def build_graph_for_studio() -> CompiledStateGraph:
    """LangGraph Studio entry point — in-memory checkpointer, no infrastructure needed."""
    from langgraph.checkpoint.memory import MemorySaver

    return build_graph(checkpointer=MemorySaver())
