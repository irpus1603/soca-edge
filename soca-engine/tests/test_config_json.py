import json
import sys
from pathlib import Path
import pytest


def test_load_config_json_reads_file(tmp_path, monkeypatch):
    """_load_config_json() actually reads the file at CONFIG_JSON."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"GCS_BUCKET": "from-json", "EDGE_NAME": "test"}))

    import config as c
    monkeypatch.setattr(c, "CONFIG_JSON", cfg_file)

    result = c._load_config_json()
    assert result["GCS_BUCKET"] == "from-json"


def test_get_prefers_config_json_over_env(tmp_path, monkeypatch):
    """_get() returns config.json value over env var."""
    cfg = {"GCS_BUCKET": "from-json", "EDGE_NAME": "test-edge"}
    import config as c
    monkeypatch.setenv("GCS_BUCKET", "from-env")
    monkeypatch.setattr(c, "_cfg", cfg)

    assert c._get("GCS_BUCKET") == "from-json"


def test_get_falls_back_to_env(monkeypatch):
    """_get() falls back to env var when key not in _cfg."""
    monkeypatch.setenv("REDIS_URL", "redis://test:6379")
    import config as c
    monkeypatch.setattr(c, "_cfg", {})
    assert c._get("REDIS_URL") == "redis://test:6379"


def test_load_config_json_warns_on_malformed(tmp_path, monkeypatch, capsys):
    """_load_config_json() prints a warning and returns {} for malformed JSON."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{not valid json}")

    import config as c
    monkeypatch.setattr(c, "CONFIG_JSON", cfg_file)

    result = c._load_config_json()
    assert result == {}
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
