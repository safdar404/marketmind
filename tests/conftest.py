import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings.from_env(require_key=False, api_key="sk-test-not-real-000000", runs_dir=tmp_path / "runs")
