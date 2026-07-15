from crewai_web_search.tools import WebSearchTool
from crewai_web_search.tools.custom_tool import WebSearchInputSchema


class TestTools:
    def test_dummy_web_search(self):
        query = "OpenShift"
        result = WebSearchTool().run(query)
        assert "Red Hat OpenShift AI" in result[0]

    def test_query_coerces_dict_to_string(self):
        """Smaller models may pass the schema dict instead of a string."""
        schema_dict = {
            "description": "The search query string to look up on the web.",
            "type": "str",
        }
        parsed = WebSearchInputSchema(query=schema_dict)
        assert isinstance(parsed.query, str)
