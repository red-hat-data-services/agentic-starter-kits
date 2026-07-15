from src.openai_responses_agent.tools import search_price, search_reviews


class TestTools:
    def test_search_price_returns_price(self):
        result = search_price("Nike")
        assert "Nike" in result
        assert "$400" in result

    def test_search_reviews_returns_reviews(self):
        result = search_reviews("Nike")
        assert "Nike" in result
        assert "good" in result

    def test_search_price_different_brand(self):
        result = search_price("Adidas")
        assert "Adidas" in result

    def test_search_reviews_different_brand(self):
        result = search_reviews("Adidas")
        assert "Adidas" in result
