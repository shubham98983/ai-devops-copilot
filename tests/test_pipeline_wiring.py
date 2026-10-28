"""Checks that the installer wired the pipeline into the real application."""
from fastapi.testclient import TestClient

from app.main import app


def test_pipeline_routes_are_not_hidden_behind_the_static_mount():
    response = TestClient(app).get("/api/repos/nobody__nothing/pipeline/runs")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "not found" in response.json()["detail"].lower()


def test_frontend_has_the_pipeline_tab():
    html = TestClient(app).get("/").text
    assert 'data-mode="pipeline"' in html and "pipeline.js" in html
    assert TestClient(app).get("/pipeline.js").status_code == 200
    assert TestClient(app).get("/pipeline.css").status_code == 200
