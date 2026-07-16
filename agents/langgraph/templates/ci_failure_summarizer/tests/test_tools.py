from ci_failure_summarizer import dummy_web_search


class TestTools:
    def test_dummy_web_search(self):
        query = "Red Hat"
        result = dummy_web_search.invoke(query)
        assert "Red Hat" in result[0]  # Check if the result contains 'Red Hat'
