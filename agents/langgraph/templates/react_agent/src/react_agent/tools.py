import re

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# SQL statement patterns — match keyword pairs that indicate real SQL statements,
# not normal English usage (e.g. "DROP TABLE" but not "drop shipping").
_SQL_PATTERNS = re.compile(
    r"""
    \b(?:
        DROP\s+(?:TABLE|DATABASE|INDEX|VIEW|SCHEMA|COLUMN)
      | SELECT\s+(?:\*|[\w]+(?:\.[\w]+)?(?:\s+AS\s+\w+)?(?:\s*,\s*[\w]+(?:\.[\w]+)?(?:\s+AS\s+\w+)?)+)\s+FROM\b
      | SELECT\s+[\w]+(?:\.[\w]+)?\s+FROM\s+[\w]+(?:\s*;|\s+(?:WHERE|ORDER|GROUP|HAVING|LIMIT|JOIN|ON|INNER|LEFT|RIGHT|CROSS)\b)
      | INSERT\s+INTO\b
      | DELETE\s+FROM\b
      | UPDATE\s+\S+\s+SET\b
      | ALTER\s+(?:TABLE|DATABASE|INDEX)\b
      | CREATE\s+(?:TABLE|DATABASE|INDEX|VIEW)\b
      | TRUNCATE\s+TABLE\b
      | UNION\s+SELECT\b
      | EXEC(?:UTE)?\s*\(
      | ;\s*--
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Shell command / code-injection patterns.
_SHELL_PATTERNS = re.compile(
    r"""
    (?:^|\s)(?:rm\s+-\w*[rf])           # rm with dangerous flags
  | (?:^|\s)sudo\s+(?:rm|cat|bash|sh|zsh  # sudo + known command
                    |python|curl|wget
                    |kill|dd|chmod|chown
                    |su|mount|mv|cp
                    |mkdir|ln|exec|tee|nc)\b
  | (?:^|\s)chmod\s+[0-7+-]               # chmod with mode arg
  | (?:^|\s)chown\s+\w+[:.]\w*            # chown with user:group
  | (?:^|\s)(?:curl|wget)\s+\S+.*\|\s*   # pipe from network
  | `[^`]+`                              # backtick execution
  | \$\([^)]+\)                          # $(...) subshell
  | \|\s*(?:bash|sh|zsh|exec)\b          # pipe to shell
  | >\s*/                                # redirect to absolute path
  | ;\s*(?:rm|cat|echo|curl|wget|python|node)\b  # chained commands
    """,
    re.IGNORECASE | re.VERBOSE,
)

REJECTION_MESSAGE = (
    "ERROR: Query rejected — the search tool does not execute SQL, "
    "shell commands, or code. Please provide a natural-language search topic."
)


def _is_dangerous_query(query: str) -> bool:
    """Return True if *query* looks like an injection payload."""
    return bool(_SQL_PATTERNS.search(query) or _SHELL_PATTERNS.search(query))


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
    if _is_dangerous_query(query):
        return REJECTION_MESSAGE
    return "FINAL ANSWER: RedHat OpenShift AI. No further search needed."
