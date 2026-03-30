import os
import pytest
from fastapi.testclient import TestClient


def test_labels_from_names_file(tmp_path):
    model_pt = tmp_path / "yolov8n.pt"
    model_pt.touch()
    names_file = tmp_path / "yolov8n.names"
    names_file.write_text("person\ncar\ntruck\n")

    from main import app
    client = TestClient(app)
    resp = client.get(f"/models/labels/?path={model_pt}")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0] == {"id": 0, "name": "person"}
    assert data[2] == {"id": 2, "name": "truck"}


def test_labels_from_yaml(tmp_path):
    model_pt = tmp_path / "best.pt"
    model_pt.touch()
    yaml_file = tmp_path / "data.yaml"
    yaml_file.write_text("names:\n  0: person\n  2: car\n")

    from main import app
    client = TestClient(app)
    resp = client.get(f"/models/labels/?path={model_pt}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(d['name'] == 'person' for d in data)


def test_labels_not_found_returns_empty(tmp_path):
    from main import app
    client = TestClient(app)
    resp = client.get(f"/models/labels/?path={tmp_path}/nonexistent.pt")
    assert resp.status_code == 200
    assert resp.json() == []
