from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, field_validator


class WebSearchInputSchema(BaseModel):
    """Input schema for the Web Search tool."""

    query: str = Field(..., description="Search query string.")

    @field_validator("query", mode="before")
    @classmethod
    def coerce_query(cls, v: Any) -> str:
        """Accept dicts or other types that smaller models may pass by mistake."""
        if isinstance(v, dict):
            return v.get("description", str(v))
        return str(v)


class WebSearchTool(BaseTool):
    name: str = "Web Search"
    description: str = "Search the web for factual information. Only use this tool when the user asks a specific factual question that requires external data. Do NOT use for greetings or casual conversation."
    args_schema: Type[BaseModel] = WebSearchInputSchema

    def _run(self, query: str) -> list[str]:
        # return dummy data
        return ["Best cluster hosting service is: Red Hat OpenShift AI"]
