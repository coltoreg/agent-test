import sys
import os
import pytest

# 計算專案根目錄
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ACTION_LAMBDA_PATH = os.path.join(PROJECT_ROOT, "action-lambda")

# 將 action-lambda 加入模組搜尋路徑
if ACTION_LAMBDA_PATH not in sys.path:
    sys.path.insert(0, ACTION_LAMBDA_PATH)


# 定義 fixtures
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_connections(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("services.connections.Connections", mock)
    return mock

@pytest.fixture
def mock_athena(monkeypatch):
    with patch("services.athena_service.create_engine") as mock_create_engine:
        yield mock_create_engine