from fastapi.testclient import TestClient

from dau_archive.app import app
from dau_archive.auth import create_user
from dau_archive.secrets import gemini_key, settings_path


def _login(client, name):
    response = client.post("/api/auth/login", json={
        "username": name, "password": "password-for-tests",
    })
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_admin_only_gemini_key_is_not_exposed(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAU_RUN_WORKER", "0")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as client:
        create_user("administrator", "password-for-tests", "admin", "Văn thư")
        create_user("staff", "password-for-tests", "staff", "Văn thư")
        admin = _login(client, "administrator")
        staff = _login(client, "staff")
        path = "/api/admin/settings/gemini"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=staff).status_code == 403
        assert client.put(path, headers=staff, json={"api_key": "test-secret-12345"}).status_code == 403
        saved = client.put(path, headers=admin, json={"api_key": "test-secret-12345"})
        assert saved.status_code == 200
        assert saved.json()["configured"] is True
        assert "test-secret-12345" not in saved.text
        assert "test-secret-12345" not in client.get(path, headers=admin).text
        assert gemini_key() == "test-secret-12345"
        assert settings_path().stat().st_mode & 0o077 == 0
        class GoogleResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(request, timeout):
            assert request.get_header("X-goog-api-key") == "test-secret-12345"
            assert "test-secret-12345" not in request.full_url
            return GoogleResponse()

        monkeypatch.setattr("dau_archive.app.urllib.request.urlopen", fake_open)
        assert client.post(path + "/test", headers=staff).status_code == 403
        assert client.post(path + "/test", headers=admin).json() == {
            "ok": True, "model": "gemini-3.8-flash",
        }
        deleted = client.delete(path, headers=admin)
        assert deleted.status_code == 200
        assert deleted.json()["configured"] is False
        assert not settings_path().exists()
