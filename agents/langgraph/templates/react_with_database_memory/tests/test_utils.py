import pytest
from react_with_database_memory.utils import get_database_uri

POSTGRES_VARS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "testdb",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "pass",
}


class TestGetDatabaseUri:
    def test_returns_uri_when_all_vars_set(self, monkeypatch):
        for key, val in POSTGRES_VARS.items():
            monkeypatch.setenv(key, val)
        uri = get_database_uri()
        assert uri == "postgresql://user:pass@localhost:5432/testdb"

    def test_url_encodes_special_characters(self, monkeypatch):
        for key, val in POSTGRES_VARS.items():
            monkeypatch.setenv(key, val)
        monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w0rd/!")
        uri = get_database_uri()
        assert "p%40ss%3Aw0rd%2F%21" in uri

    def test_raises_when_all_vars_missing(self, monkeypatch):
        for key in POSTGRES_VARS:
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(ValueError, match="POSTGRES_HOST"):
            get_database_uri()

    def test_raises_with_single_missing_var(self, monkeypatch):
        for key, val in POSTGRES_VARS.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv("POSTGRES_PASSWORD")
        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            get_database_uri()

    def test_raises_lists_all_missing_vars(self, monkeypatch):
        for key in POSTGRES_VARS:
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(ValueError) as exc_info:
            get_database_uri()
        for var in POSTGRES_VARS:
            assert var in str(exc_info.value)
