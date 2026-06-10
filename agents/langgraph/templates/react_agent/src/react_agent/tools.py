from langchain_core.tools import tool
from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    """Schema for the search tool input."""

    query: str = Field(description="The value to search for.")


@tool("search", parse_docstring=True)
def dummy_web_search(query: str) -> str:
    """Search the web for information about a specific topic.

    Placeholder implementation used by the ReAct agent; returns a fixed list
    for demonstration. Replace with a real search API in production.

    Args:
        query: The specific text string to search for. Example: "RedHat"

    Returns:
        A list of result strings (currently a single placeholder).
    """
    return "FINAL ANSWER: RedHat OpenShift AI. No further search needed."
