import pytest
from handlers.query_glue_table import query_glue_table_handler
from utils.exceptions import ValidationError

def test_query_handler_success(monkeypatch):
    fake_result = {"sql_query": "SELECT 1", "answer": "yes"}
    monkeypatch.setattr("services.athena_service.AthenaService.execute_query", lambda self, q: fake_result)

    event = {"inputText": "some query", "sessionAttributes": {}, "parameters": []}
    result, session_attrs = query_glue_table_handler(event, {})
    assert result["sql_query"] == "SELECT 1"
    assert session_attrs["last_query_text"] == "some query"

def test_query_handler_missing_input():
    event = {"inputText": "", "sessionAttributes": {}, "parameters": []}
    with pytest.raises(ValidationError):
        query_glue_table_handler(event, {})
