from langchain_core.tools import tool


@tool("create_file")
def create_file(filename: str, content: str) -> str:
    """Create a file. Requires human approval."""
    return "After confirmation file was created"
