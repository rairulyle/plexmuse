"""
Tests for FastAPI endpoints
"""

# pylint: disable=redefined-outer-name,unused-argument

import os
from unittest.mock import patch

import pytest  # pylint: disable=import-error
from fastapi.testclient import TestClient

from app.main import app
from app.models import Artist

client = TestClient(app)


@pytest.fixture
def mock_env():
    """Mock environment variables"""
    with patch.dict(os.environ, {"PLEX_BASE_URL": "http://plex:32400", "PLEX_TOKEN": "test-token"}):
        yield


@pytest.fixture(autouse=True)
def mock_plex_service():
    """Mock PlexService methods"""
    with patch("app.main.plex_service") as mock:
        # Setup common mock returns
        mock.get_cache_size.return_value = 100
        mock.get_all_artists.return_value = [
            Artist(id="1", name="Artist 1", genres=["Rock"]),
            Artist(id="2", name="Artist 2", genres=["Pop"]),
        ]
        mock.machine_identifier = "test-machine"
        mock.initialize.return_value = None  # Mock the initialize method
        yield mock


@pytest.fixture
def mock_llm_service():
    """Mock LLMService methods"""
    with patch("app.main.llm_service") as mock:
        # Setup common mock returns
        mock.get_artist_recommendations.return_value = ["Artist 1", "Artist 2"]
        mock.get_track_recommendations.return_value = [
            {"artist": "Artist 1", "title": "Song 1"},
            {"artist": "Artist 2", "title": "Song 2"},
        ]
        mock.generate_playlist_name.return_value = "Test Playlist"
        yield mock


def test_health_check(mock_plex_service):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "cache_size": 100}


def test_get_artists(mock_plex_service):
    """Test getting all artists"""
    response = client.get("/artists")
    assert response.status_code == 200
    artists = response.json()
    assert len(artists) == 2
    assert artists[0]["name"] == "Artist 1"
    assert artists[1]["name"] == "Artist 2"


def test_create_recommendations(mock_plex_service, mock_llm_service):
    """Test creating playlist recommendations"""
    # Mock playlist creation
    mock_playlist = type("MockPlaylist", (), {"title": "Test Playlist", "ratingKey": "123"})()
    mock_plex_service.create_curated_playlist.return_value = mock_playlist

    request_data = {"prompt": "Create a rock playlist", "model": "gpt-4o", "min_tracks": 2, "max_tracks": 5}

    response = client.post("/recommendations", json=request_data)
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Test Playlist"
    assert data["track_count"] == 2
    assert data["id"] == "123"
    assert data["machine_identifier"] == "test-machine"
    assert len(data["tracks"]) == 2


def test_create_recommendations_error(mock_plex_service, mock_llm_service):
    """Test error handling in recommendations endpoint"""
    mock_llm_service.get_artist_recommendations.side_effect = Exception("LLM error")

    request_data = {"prompt": "Create a rock playlist", "model": "gpt-4o", "min_tracks": 2, "max_tracks": 5}

    response = client.post("/recommendations", json=request_data)
    assert response.status_code == 500
    assert "LLM error" in response.json()["detail"]


def test_root_endpoint(mock_env):
    """Test root endpoint serving HTML"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"

    # Check if Plex configuration is injected
    content = response.text
    assert "window.plexBaseUrl" in content
    assert "window.plexToken" in content
    assert "http://plex:32400" in content
    assert "test-token" in content


def test_get_providers_all_configured():
    """Test providers endpoint when all API keys are configured"""
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "test-openai-key",
            "ANTHROPIC_API_KEY": "test-anthropic-key",
            "GEMINI_API_KEY": "test-gemini-key",
        },
    ):
        response = client.get("/providers")
        assert response.status_code == 200
        providers = response.json()
        # 3 OpenAI + 2 Anthropic + 1 Gemini = 6 providers
        assert len(providers) == 6

        # Check OpenAI providers exist
        openai_providers = [p for p in providers if p["id"].startswith("openai")]
        assert len(openai_providers) == 3
        assert any("gpt" in p["model"] for p in openai_providers)

        # Check Anthropic providers exist
        anthropic_providers = [p for p in providers if p["id"].startswith("anthropic")]
        assert len(anthropic_providers) == 2
        assert any("claude" in p["model"] for p in anthropic_providers)

        # Check Gemini provider exists
        gemini_providers = [p for p in providers if p["id"].startswith("gemini")]
        assert len(gemini_providers) == 1
        assert "gemini" in gemini_providers[0]["model"]

        # Check temperature field exists
        assert all("temperature" in p for p in providers)


def test_get_providers_partial_configured():
    """Test providers endpoint when only some API keys are configured"""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}, clear=True):
        response = client.get("/providers")
        assert response.status_code == 200
        providers = response.json()
        # 3 OpenAI models
        assert len(providers) == 3
        assert all(p["id"].startswith("openai") for p in providers)


def test_get_providers_none_configured():
    """Test providers endpoint when no API keys are configured"""
    with patch.dict(os.environ, {}, clear=True):
        response = client.get("/providers")
        assert response.status_code == 200
        providers = response.json()
        assert len(providers) == 0


def test_create_recommendations_missing_model(mock_plex_service):
    """Test that missing model field returns 422 validation error"""
    request_data = {"prompt": "Create a rock playlist", "min_tracks": 2, "max_tracks": 5}

    response = client.post("/recommendations", json=request_data)
    assert response.status_code == 422

    error_detail = response.json()["detail"]
    assert any(err["loc"] == ["body", "model"] for err in error_detail)
