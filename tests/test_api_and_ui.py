"""API endpoints through FastAPI's TestClient, and a headless render of every UI page."""
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKEHOUSE_ROOT", str(tmp_path / "lakehouse"))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("BOOTSTRAP", "false")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", (tmp_path / "mlruns").as_uri())
    import goldenrecord.config
    import goldenrecord.store
    import goldenrecord.api
    importlib.reload(goldenrecord.config)
    importlib.reload(goldenrecord.store)
    api = importlib.reload(goldenrecord.api)
    with TestClient(api.app) as c:
        yield c


def test_full_api_flow(client):
    assert client.get("/health").json()["llm"] == "none (rules only)"
    gen = client.post("/data/generate", json={"vendors": 200, "invoices": 1500, "seed": 3}).json()
    assert gen["vendor_records"] > 200
    run = client.post("/runs").json()
    assert run["summary"]["golden_vendors"] > 0
    assert client.get("/runs").json()[0]["run_id"] == run["summary"]["run_id"]

    queue = client.get("/review/queue").json()
    if queue:
        pair = {"left_key": queue[0]["left_key"], "right_key": queue[0]["right_key"]}
        assert client.post("/review/recommend", json=pair).json()["recommendation"] in ("match", "no_match", "unsure")
        ok = client.post("/review/decisions", json={**pair, "decision": "match", "reviewer": "t"})
        assert ok.status_code == 200
        bad = client.post("/review/decisions", json={**pair, "decision": "maybe", "reviewer": "t"})
        assert bad.status_code == 400

    draft = client.post("/rules/draft", json={"text": "Vendor phone must not be empty"}).json()
    assert draft["ok"] and draft["rule"]["column"] == "phone" and "fail_rate" in draft["preview"]

    patterns = client.get("/patterns").json()
    assert patterns
    fix = next(p for p in patterns if p["kind"] in ("record_fix", "acknowledge"))
    decided = client.post(f"/patterns/{fix['pattern_id']}/decision", json={"decision": "approve", "reviewer": "t"})
    assert decided.status_code == 200 and decided.json()["library_version"] >= 1
    assert client.get("/library").json()[0]["item_id"] == decided.json()["item_id"]
    xref_key = client.get("/golden/GRV-000001")
    assert xref_key.status_code == 200 and xref_key.json()["members"]
    assert client.post("/demo/bad-batch?rows=300").json()["rows"] == 300
    assert client.delete("/demo/bad-batch").json()["removed"] is True
    assert client.post("/learning/train").json()["ok"] is False  # too few labels yet
    assert isinstance(client.get("/alerts").json(), list)


def test_ui_pages_render(client):
    from streamlit.testing.v1 import AppTest

    client.post("/data/generate", json={"vendors": 150, "invoices": 1000, "seed": 4})
    client.post("/runs")
    app_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    for page in ["Overview", "Pattern queue", "Golden records", "Rule studio", "Rule library", "Executive spend",
                 "Alerts & agents"]:
        at = AppTest.from_file(str(app_path), default_timeout=60)
        at.run()
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, f"{page}: {at.exception}"
        assert at.title[0].value
