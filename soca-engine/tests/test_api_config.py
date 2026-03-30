import base64, json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import config as c
    monkeypatch.setattr(c, "ENGINE_API_KEY", "test-key-123")
    monkeypatch.setattr(c, "BASE_DIR", tmp_path)
    monkeypatch.setattr(c, "_cfg", {})
    from main import app
    return TestClient(app)


def test_config_push_requires_auth(client):
    resp = client.post("/config", json={})
    assert resp.status_code == 403


def test_config_push_wrong_key(client):
    resp = client.post("/config", json={}, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_config_push_writes_config_json(client, tmp_path, monkeypatch):
    import config as c
    monkeypatch.setattr(c, "BASE_DIR", tmp_path)

    gcs_key_b64 = base64.b64encode(b'{"type":"service_account"}').decode()
    pubsub_key_b64 = base64.b64encode(b'{"type":"service_account"}').decode()

    resp = client.post("/config", json={
        "gcs_bucket": "my-bucket",
        "gcs_path_prefix": "edge-test",
        "gcs_key": gcs_key_b64,
        "publisher_type": "pubsub",
        "pubsub_project_id": "my-project",
        "pubsub_topic": "soca-detections",
        "pubsub_key": pubsub_key_b64,
    }, headers={"Authorization": "Bearer test-key-123"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["gcs_bucket"] == "my-bucket"
    assert cfg["publisher_type"] == "pubsub"
    assert "gcs_key_path" in cfg
    assert "pubsub_key_path" in cfg
    assert Path(cfg["gcs_key_path"]).read_bytes() == b'{"type":"service_account"}'
