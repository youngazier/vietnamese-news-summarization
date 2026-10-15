"""A deterministic review loop with independent draft and recursion ceilings."""

from typing import Literal, Protocol

from app.agents.nodes import (
    MetadataProvider,
    ReviewProvider,
    Summarizer,
    make_draft_node,
    make_review_node,
)
from app.agents.schemas import ReviewResult
from app.agents.state import NewsInput, NewsState
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

GRAPH_RECURSION_LIMIT = 8


class NewsProvider(MetadataProvider, ReviewProvider, Protocol):
    pass


def build_news_graph(
    summarizer: Summarizer,
    provider: NewsProvider,
    *,
    max_attempts: int = 2,
) -> Runnable:
    if type(max_attempts) is not int or max_attempts not in {1, 2}:
        raise ValueError("Graph supports one or two draft attempts")

    def route(state: NewsState) -> Literal["accept", "retry", "reject"]:
        attempts = state["attempts"]
        if type(attempts) is not int or not 1 <= attempts <= max_attempts:
            raise ValueError("Invalid graph draft count")
        result = ReviewResult(approved=state["approved"], feedback=state["feedback"])
        if result.approved:
            return "accept"
        return "retry" if attempts < max_attempts else "reject"

    def accept(state: NewsState) -> dict[str, object]:
        return {"outcome": "approved"}

    def reject(state: NewsState) -> dict[str, object]:
        return {"outcome": "needs_review"}

    # Only article inputs enter a new run; stale approval/attempts cannot be injected.
    builder = StateGraph(NewsState, input_schema=NewsInput)
    builder.add_node("draft", make_draft_node(summarizer, provider, max_attempts=max_attempts))
    builder.add_node("review", make_review_node(provider))
    builder.add_node("accept", accept)
    builder.add_node("reject", reject)
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "review")
    builder.add_conditional_edges(
        "review", route, {"accept": "accept", "retry": "draft", "reject": "reject"}
    )
    builder.add_edge("accept", END)
    builder.add_edge("reject", END)
    return builder.compile().with_config(recursion_limit=GRAPH_RECURSION_LIMIT)
