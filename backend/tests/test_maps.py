from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.main import create_app


def test_map_without_key_preserves_available_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "  ")
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/maps/config")
    config = response.json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert config["provider"] == "openstreetmap"
    assert config["tile_url"] == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    assert 'https://www.openstreetmap.org/copyright' in config["attribution"]
    assert "key=" not in config["tile_url"]


def test_google_maps_key_is_encoded_without_adding_parameters(tmp_path, monkeypatch):
    key = "test-public-key&another=parameter+ /"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", key)
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/maps/config")
    config = response.json()
    url = urlparse(config["script_url"])
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert config["provider"] == "google"
    assert url.netloc == "maps.googleapis.com"
    assert url.path == "/maps/api/js"
    assert parse_qs(url.query) == {
        "key": [key.strip()], "loading": ["async"], "v": ["weekly"], "language": ["es"], "region": ["PE"],
    }
    assert "tile_url" not in config
