"""Tests for marco.web.routes via FastAPI TestClient."""

import json

import pytest
from fastapi.testclient import TestClient

from marco.web.server import create_app


@pytest.fixture
def client(tmp_path):
    config = {"output_dir": str(tmp_path / "output"), "config_path": None, "log_level": "INFO"}
    app = create_app(config)
    return TestClient(app)


class TestStateEndpoint:
    def test_get_state_empty(self, client):
        resp = client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["binaries"] == []

    def test_get_state_type(self, client):
        data = client.get("/api/state").json()
        assert data["type"] == "state_snapshot"


class TestRunsEndpoint:
    def test_get_runs_empty(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_runs_with_directory(self, client, tmp_path):
        # Create a fake run directory
        run_dir = tmp_path / "output" / "test_run_20250101"
        run_dir.mkdir(parents=True)
        manifest = {"abc123": {"module": "test.dll", "path": "C:\\test.dll", "sha256": "abc123", "file_version": None}}
        (run_dir / "manifest.json").write_text(json.dumps(manifest))
        (run_dir / "nodes.jsonl").touch()

        resp = client.get("/api/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["id"] == "test_run_20250101"
        assert runs[0]["module_count"] == 1
        assert runs[0]["has_nodes"] is True
        assert runs[0]["has_edges"] is False


class TestRunManifest:
    def test_manifest_not_found(self, client):
        resp = client.get("/api/runs/nonexistent/manifest")
        assert resp.status_code == 200
        assert resp.json()["error"] == "manifest not found"

    def test_manifest_found(self, client, tmp_path):
        run_dir = tmp_path / "output" / "test_run"
        run_dir.mkdir(parents=True)
        manifest = {"sha1": {"module": "a.dll", "path": "a.dll", "sha256": "sha1", "file_version": "1.0"}}
        (run_dir / "manifest.json").write_text(json.dumps(manifest))

        resp = client.get("/api/runs/test_run/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert "sha1" in data


class TestAnalyzeEndpoint:
    def test_analyze_no_seed(self, client):
        resp = client.post("/api/analyze", json={})
        assert resp.status_code == 200
        assert resp.json()["error"] == "either seed or only list must be provided"


class TestNeo4jStatusEndpoint:
    def test_neo4j_status_disconnected(self, client):
        resp = client.get("/api/neo4j/status")
        assert resp.status_code == 200
        data = resp.json()
        # Neo4j likely not running in test environment
        assert "connected" in data


class TestDependencyGraph:
    def test_empty_graph(self, client):
        resp = client.get("/api/dependency-graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["modules"] == []
        assert data["edges"] == []


class TestWebSocket:
    def test_websocket_connects_and_receives_snapshot(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "state_snapshot"
            assert data["running"] is False


class TestStaticFiles:
    def test_index_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "marco" in resp.text
