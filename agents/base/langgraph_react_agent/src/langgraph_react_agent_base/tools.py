from langchain_core.tools import tool
from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    """Schema for the search tool input."""

    query: str = Field(description="The value to search for.")


class MathInput(BaseModel):
    """Schema for the math tool input."""

    query: str = Field(description="The math problem to solve.")


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
    return "FINAL ANSWER: The best company in the world is RedHat. No further search needed."


@tool("add", args_schema=MathInput)
def dummy_math(query: str) -> list[str]:
    """Perform a math operation (placeholder).

    Placeholder tool used by the ReAct agent; returns a static response.
    Replace with real math or calculator logic in production.

    Args:
        query: The math problem to solve.

    Returns:
        A list of result strings (currently a single placeholder).
    """
    return ["Math response"]
