"""Tier 2 council as a LangGraph: drafts fan out independently, `verify` waits for every branch, the judge runs only on a quorum."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


class CouncilState(TypedDict, total=False):
    endpoints: list[str]
    drafts: Annotated[list[Any], operator.add]  # arrival order is nondeterministic; verify restores it
    ballot: Any
    response: Any


def build(draft: Callable[[str], Awaitable[Any]],
          verify: Callable[[list[Any]], Awaitable[tuple[Any, Any]]],
          judge: Callable[[Any], Awaitable[Any]]) -> Any:
    """`draft` must never raise: an exception here would fail the superstep and lose the other members' work."""

    async def draft_node(s: dict[str, Any]) -> dict[str, Any]:
        return {"drafts": [await draft(s["endpoint"])]}

    async def verify_node(s: CouncilState) -> dict[str, Any]:
        ballot, response = await verify(s.get("drafts", []))
        return {"ballot": ballot, "response": response}

    async def judge_node(s: CouncilState) -> dict[str, Any]:
        return {"response": await judge(s["ballot"])}

    def fan_out(s: CouncilState) -> list[Send] | str:
        return [Send("draft", {"endpoint": e}) for e in s["endpoints"]] or "verify"

    g = StateGraph(CouncilState)
    g.add_node("draft", draft_node)
    g.add_node("verify", verify_node, defer=True)  # not a list-join edge: that never fires when a branch is skipped
    g.add_node("judge", judge_node)
    g.add_conditional_edges(START, fan_out, ["draft", "verify"])
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", lambda s: END if s.get("response") is not None else "judge", ["judge", END])
    g.add_edge("judge", END)
    return g.compile()
