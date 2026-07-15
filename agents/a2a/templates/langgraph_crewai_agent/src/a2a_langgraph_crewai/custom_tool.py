"""Dummy Web Search tool for the CrewAI A2A specialist (no real HTTP)."""

from __future__ import annotations

from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, field_validator


class WebSearchInputSchema(BaseModel):
    query: str = Field(..., description="Search query string.")

    @field_validator("query", mode="before")
    @classmethod
    def coerce_query(cls, v: Any) -> str:
        if isinstance(v, dict):
            return v.get("description", str(v))
        return str(v)


class DummyWebSearchTool(BaseTool):
    name: str = "Web Search"
    description: str = (
        "Search the web for factual information. Use when the user needs external facts. "
        "Do NOT use for greetings or casual conversation."
    )
    args_schema: Type[BaseModel] = WebSearchInputSchema

    def _run(self, query: str) -> list[str]:
        _ = query
        return ["Red Hat after encryption is Uhg_Kdw-07"]
