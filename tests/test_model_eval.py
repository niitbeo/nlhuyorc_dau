from fastapi.testclient import TestClient

from dau_archive import model_eval
from dau_archive.app import app
from dau_archive.auth import create_user


def _login(client, username):
    result = client.post("/api/auth/login", json={
        "username": username, "password": "password-for-tests"})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json()["token"]}


def test_model_check_is_admin_only_and_bounds_work(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    monkeypatch.setattr(model_eval, "availability", lambda: {
        "printed": True, "handwritten": True, "gemini": False})
    monkeypatch.setattr(model_eval, "latest", lambda: None)
    calls = []

    def record(*args):
        calls.append(args)
        return {"id": "test", "status": "running"}

    monkeypatch.setattr(model_eval, "start", record)
    with TestClient(app) as client:
        create_user("model-admin", "password-for-tests", "admin", "Văn thư")
        create_user("model-staff", "password-for-tests", "staff", "Văn thư")
        admin, staff = _login(client, "model-admin"), _login(client, "model-staff")
        assert client.get("/api/admin/model-check", headers=staff).status_code == 403
        assert client.post("/api/admin/model-check", headers=staff, json={}).status_code == 403
        assert client.get("/api/admin/model-check", headers=admin).status_code == 200
        assert client.post("/api/admin/model-check", headers=admin,
                           json={"printed_count": 100}).status_code == 422
        started = client.post("/api/admin/model-check", headers=admin,
                              json={"printed_count": 2, "handwritten_count": 3})
        assert started.status_code == 202
        assert calls == [(2, 3, False)]


def test_metrics_count_vietnamese_diacritics():
    perfect = model_eval.score("CỘNG HÒA", "CỘNG HÒA", 1.25)
    changed = model_eval.score("CỘNG HÒA", "CỘNG HOA", 1.25)
    assert perfect["cer"] == perfect["wer"] == 0
    assert changed["cer"] > 0 and changed["wer"] > 0
