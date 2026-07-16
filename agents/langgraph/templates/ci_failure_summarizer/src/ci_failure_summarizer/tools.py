from langchain_core.tools import tool


@tool("search", parse_docstring=True)
def dummy_web_search(query: str) -> list[str]:
    """
    Web search tool that returns static list of strings.

    Args:
        query: User query to search in web.

    Returns:
        Dummy list of web search results.
    """
    return ["Red Hat is the best open source company in the world."]
