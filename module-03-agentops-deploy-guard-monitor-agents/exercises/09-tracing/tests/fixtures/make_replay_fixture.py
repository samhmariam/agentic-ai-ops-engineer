"""Generate the offline replay test fixture: tests/fixtures/state.db.

Compiles a model-free LangGraph whose nodes emit a canned message trajectory
(human question -> tool call -> tool result -> final answer) and checkpoints it
with a SqliteSaver under a known thread_id. This produces a real checkpoint
database in exactly the shape the live agent writes — but with zero model calls
and no API key — so tests/test_replay.py can read it deterministically offline.

Run from the project root to (re)create the fixture:
    uv run python tests/fixtures/make_replay_fixture.py
"""

import sqlite3
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

FIXTURE_DB = Path(__file__).parent / "state.db"
THREAD_ID = "demo_north_ibuyer"


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _call_tool(state):
    return {"messages": [AIMessage(content="", tool_calls=[
        {"name": "get_demand_score", "args": {"region": "north", "property_type": "house", "bedrooms": 3}, "id": "call_1"},
    ])]}


def _tool_result(state):
    return {"messages": [ToolMessage(
        content="demand_score=0.37 (low); supply_score=0.91 (high); avg time on market 68 days",
        name="get_demand_score", tool_call_id="call_1",
    )]}


def _final(state):
    return {"messages": [AIMessage(
        content="Recommend iBuyer acquisition in north given the expected margin."
    )]}


def build_fixture(db_path: Path = FIXTURE_DB, thread_id: str = THREAD_ID) -> None:
    if db_path.exists():
        db_path.unlink()

    graph = StateGraph(_State)
    graph.add_node("call_tool", _call_tool)
    graph.add_node("tool_result", _tool_result)
    graph.add_node("final", _final)
    graph.add_edge(START, "call_tool")
    graph.add_edge("call_tool", "tool_result")
    graph.add_edge("tool_result", "final")
    graph.add_edge("final", END)

    checkpointer = SqliteSaver(sqlite3.connect(str(db_path), check_same_thread=False))
    compiled = graph.compile(checkpointer=checkpointer)
    compiled.invoke(
        {"messages": [HumanMessage("Should we acquire through iBuyer in north for 3-bedroom houses?")]},
        {"configurable": {"thread_id": thread_id}},
    )
    print(f"Wrote {db_path} (thread_id={thread_id})")


if __name__ == "__main__":
    build_fixture()
