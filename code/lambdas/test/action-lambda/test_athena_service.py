import pytest
from services.athena_service import AthenaService
from utils.exceptions import ValidationError, ExternalAPIError

def test_execute_query_success(mock_athena_service, mock_query_result):
    mock_athena_service.query_engine.query.return_value = type("Result", (), mock_query_result)
    result = mock_athena_service.execute_query("查詢 Company A 市佔率")
    assert result["sql_query"] == "SELECT * FROM companies"
    assert "市佔率" in result["answer"]

def test_execute_query_empty_text(mock_athena_service):
    with pytest.raises(ValidationError):
        mock_athena_service.execute_query("")

def test_execute_query_fail(mock_athena_service):
    mock_athena_service.query_engine.query.side_effect = Exception("fail")
    with pytest.raises(ExternalAPIError):
        mock_athena_service.execute_query("SELECT ...")
