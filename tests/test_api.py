from fastapi.testclient import TestClient

from omniintel.api import create_app


def test_health_is_public_and_job_creation_requires_token(tmp_path):
    app = create_app(tmp_path / "api.db", api_token="test-secret")
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    denied = client.post(
        "/v1/youtube/jobs",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk", "approve_network": True},
    )
    assert denied.status_code == 401


def test_youtube_job_requires_explicit_network_approval(tmp_path):
    app = create_app(tmp_path / "api.db", api_token="test-secret")
    client = TestClient(app)
    response = client.post(
        "/v1/youtube/jobs",
        headers={"Authorization": "Bearer test-secret"},
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk"},
    )
    assert response.status_code == 400
    assert "Explicit approval" in response.json()["detail"]


def test_youtube_job_is_queued_and_status_is_readable(tmp_path):
    app = create_app(tmp_path / "api.db", api_token="test-secret")
    client = TestClient(app)
    response = client.post(
        "/v1/youtube/jobs",
        headers={"Authorization": "Bearer test-secret", "Idempotency-Key": "lecture-1"},
        json={
            "url": "https://youtu.be/abcdefghijk",
            "approve_network": True,
            "approve_ai": False,
            "language": "en",
        },
    )
    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "QUEUED"
    status = client.get(
        created["status_url"],
        headers={"Authorization": "Bearer test-secret"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "QUEUED"


def test_api_rejects_untrusted_youtube_host(tmp_path):
    app = create_app(tmp_path / "api.db", api_token="test-secret")
    client = TestClient(app)
    response = client.post(
        "/v1/youtube/jobs",
        headers={"Authorization": "Bearer test-secret"},
        json={"url": "https://youtube.com.attacker.example/watch?v=abcdefghijk", "approve_network": True},
    )
    assert response.status_code == 422


def test_authorized_media_upload_creates_a_durable_transcription_job(tmp_path):
    app = create_app(tmp_path / "api.db", api_token="test-secret")
    client = TestClient(app)
    response = client.post(
        "/v1/media/jobs",
        headers={"Authorization": "Bearer test-secret"},
        data={"approve_ai": "false", "language": "en", "title": "Lecture"},
        files={"file": ("lecture.mp4", b"not-a-real-video-yet", "video/mp4")},
    )
    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "QUEUED"
    status = client.get(
        created["status_url"],
        headers={"Authorization": "Bearer test-secret"},
    )
    assert status.status_code == 200
    assert status.json()["job_type"] == "UPLOADED_MEDIA_TO_NOTES"


def test_media_upload_rejects_non_media_content_type(tmp_path):
    app = create_app(tmp_path / "api.db", api_token="test-secret")
    client = TestClient(app)
    response = client.post(
        "/v1/media/jobs",
        headers={"Authorization": "Bearer test-secret"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_ai_provider_ollama_does_not_require_cloud_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIINTEL_AI_PROVIDER", "ollama")
    monkeypatch.delenv("OMNIINTEL_OPENAI_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path / "api.db", api_token="test-secret"))
    response = client.post("/v1/youtube/jobs", headers={"Authorization": "Bearer test-secret"},
        json={"url": "https://youtu.be/abcdefghijk", "approve_network": True, "approve_ai": True})
    assert response.status_code == 202


def test_unknown_ai_provider_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIINTEL_AI_PROVIDER", "unknown-provider")
    monkeypatch.setenv("OMNIINTEL_OPENAI_API_KEY", "configured")
    client = TestClient(create_app(tmp_path / "api.db", api_token="test-secret"))
    response = client.post("/v1/youtube/jobs", headers={"Authorization": "Bearer test-secret"},
        json={"url": "https://youtu.be/abcdefghijk", "approve_network": True, "approve_ai": True})
    assert response.status_code == 503
