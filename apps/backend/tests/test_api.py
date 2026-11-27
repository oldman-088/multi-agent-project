from fastapi.testclient import TestClient

from app.main import create_app
from app.services.store import Store


def setup_client(tmp_path, monkeypatch, org="org-a"):
    monkeypatch.setenv("AATM_API_TOKEN", "test-token")
    monkeypatch.setenv("AATM_ORGANIZATION_ID", org)
    store = Store(str(tmp_path / "test.sqlite3"))
    return TestClient(create_app(store))


def headers():
    return {"Authorization": "Bearer test-token"}


def test_requires_auth_for_agents_and_runs(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    assert client.post("/api/agents", json={"name": "bot"}).status_code == 401
    assert client.get("/api/runs/missing/events").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_agents_versions_runs_and_replayable_events(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    agent = client.post("/api/agents", headers=headers(), json={"name": "helper", "instructions": "help"})
    assert agent.status_code == 201
    agent_data = agent.json()
    assert client.get(f"/api/agents/{agent_data['id']}/versions", headers=headers()).status_code == 200
    run = client.post("/api/runs", headers=headers(), json={"agent_id": agent_data["id"]}).json()
    first = client.post(f"/api/runs/{run['id']}/messages", headers=headers(), json={"content": "hello"})
    second = client.post(f"/api/runs/{run['id']}/messages", headers=headers(), json={"content": "again"})
    assert (first.json()["sequence"], second.json()["sequence"]) == (1, 2)
    replay = client.get(f"/api/runs/{run['id']}/events?after_sequence=1", headers=headers()).json()
    assert [event["sequence"] for event in replay["events"]] == [2]
    assert replay["next_sequence"] == 2
    approval = client.post(f"/api/runs/{run['id']}/tool-approvals", headers=headers(), json={"tool_name": "search", "arguments": {"query": "abc"}})
    assert approval.status_code == 201
    approved = client.post(f"/api/runs/{run['id']}/approvals/{approval.json()['id']}", headers=headers())
    assert approved.json()["status"] == "approved"
    all_events = client.get(f"/api/runs/{run['id']}/events", headers=headers()).json()["events"]
    assert [event["sequence"] for event in all_events] == [1, 2, 3, 4]


def test_organization_isolation_returns_not_found(tmp_path, monkeypatch):
    client_a = setup_client(tmp_path, monkeypatch, "org-a")
    agent = client_a.post("/api/agents", headers=headers(), json={"name": "private"}).json()
    monkeypatch.setenv("AATM_ORGANIZATION_ID", "org-b")
    client_b = TestClient(create_app(Store(str(tmp_path / "test.sqlite3"))))
    assert client_b.get("/api/agents", headers=headers()).json() == []
    assert client_b.get(f"/api/agents/{agent['id']}/versions", headers=headers()).status_code == 404
    assert client_b.post("/api/runs", headers=headers(), json={"agent_id": agent["id"]}).status_code == 404
