"""Tests for the Plex service."""

# pylint: disable=protected-access,redefined-outer-name

import logging
from unittest.mock import Mock, MagicMock, patch

import pytest  # pylint: disable=import-error

from app.models import Artist
from app.services.plex_service import PlexService, normalize_title, find_best_track_match

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def test_normalize_title():
    """Test title normalization function."""
    assert normalize_title("Track (Live Version)") == "track"
    assert normalize_title("Track.with.dots") == "track with dots"
    assert normalize_title("Track,with,commas") == "track with commas"
    assert normalize_title("  Extra  Spaces  ") == "extra spaces"


def test_find_best_track_match():
    """Test track matching function."""
    # Create mock tracks
    track1 = Mock(title="Perfect Match")
    track2 = Mock(title="Close Match (Live)")
    track3 = Mock(title="Different Track")
    tracks = [track1, track2, track3]

    # Test exact match
    match, score = find_best_track_match(tracks, "Perfect Match")
    assert match == track1
    assert score == 1.0

    # Test close match
    match, score = find_best_track_match(tracks, "Close Match")
    assert match == track2
    assert score >= 0.85

    # Test no match
    match, score = find_best_track_match(tracks, "Non Existent Track")
    assert match is None
    assert score == 0


@pytest.fixture
def mock_plex_server():
    """Fixture to create a mock Plex server."""
    with patch("app.services.plex_service.PlexServer") as mock_server:
        # Mock the machine identifier
        mock_server.return_value.machineIdentifier = "mock_machine_id"

        # Create mock library section
        mock_library = Mock()
        mock_server.return_value.library.section.return_value = mock_library

        yield mock_server, mock_library


@pytest.fixture
def plex_service(mock_plex_server):  # pylint: disable=unused-argument
    """Fixture to create a PlexService instance with mocked server."""
    service = PlexService("http://localhost:32400", "fake_token")
    return service


def test_plex_service_initialization(plex_service, mock_plex_server):  # pylint: disable=unused-argument
    """Test PlexService initialization."""
    _, mock_library = mock_plex_server

    # Mock artists for initialization
    artist1 = Mock(ratingKey="1", title="Artist1")
    artist1.genres = []  # Initialize as empty list
    mock_genre1 = Mock(tag="Rock")
    mock_genre2 = Mock(tag="Alternative")
    artist1.genres.extend([mock_genre1, mock_genre2])

    artist2 = Mock(ratingKey="2", title="Artist2")
    artist2.genres = []  # Initialize as empty list
    mock_genre3 = Mock(tag="Pop")
    artist2.genres.append(mock_genre3)

    mock_library.search.return_value = [artist1, artist2]

    # Initialize service
    plex_service.initialize()

    # Verify cache was populated
    assert plex_service.get_cache_size() == 2
    assert "1" in plex_service._artists_cache
    assert "2" in plex_service._artists_cache


def test_get_all_artists(plex_service):
    """Test retrieving all artists from cache."""
    # Populate cache with test data
    plex_service._artists_cache = {
        "1": Artist(id="1", name="Artist1", genres=["Rock"]),
        "2": Artist(id="2", name="Artist2", genres=["Pop"]),
    }

    artists = plex_service.get_all_artists()
    assert len(artists) == 2
    assert any(a.name == "Artist1" for a in artists)
    assert any(a.name == "Artist2" for a in artists)


def test_get_artists_albums_bulk(plex_service, mock_plex_server):
    """Test bulk album retrieval."""
    mock_server, mock_library = mock_plex_server

    # Setup mock artists in cache
    artist1 = Mock(title="Artist1", genres=[])  # Initialize with empty list
    album1 = Mock(title="Album1", year=2020)
    album1.tracks = Mock(return_value=["track1", "track2"])

    # Set up albums as a method that returns a list
    artist1.albums.return_value = [album1]

    # Setup mock search results
    mock_library.search.return_value = [artist1]

    # Initialize plex service
    plex_service.initialize()
    plex_service._music_library = mock_library
    plex_service._server = mock_server.return_value

    # Add artist to cache
    plex_service._artists_cache = {"1": Artist(id="1", name="Artist1", genres=["Rock"])}

    # Test album retrieval
    albums = plex_service.get_artists_albums_bulk(["Artist1"])

    assert "Artist1" in albums
    assert len(albums["Artist1"]) == 1
    assert albums["Artist1"][0]["name"] == "Album1"
    assert albums["Artist1"][0]["year"] == 2020
    assert albums["Artist1"][0]["track_count"] == 2


def test_create_curated_playlist(plex_service, mock_plex_server):
    """Test playlist creation with track matching."""
    mock_server, mock_library = mock_plex_server

    # Setup mock track
    track1 = MagicMock()
    track1.title = "Track1"
    track1.artist.return_value = MagicMock(title="Artist1")

    # Setup mock album
    album = MagicMock()
    album.tracks.return_value = [track1]

    # Create artist with mock albums
    search_result_artist = MagicMock()
    search_result_artist.title = "Artist1"
    search_result_artist.genres = []
    search_result_artist.albums.return_value = [album]

    # Setup mock searches - we need to handle different search scenarios
    def mock_search(*args, **kwargs):  # pylint: disable=unused-argument
        if kwargs.get("libtype") == "artist":
            return [search_result_artist]
        if kwargs.get("libtype") == "track":
            return [track1]
        return []

    # Use side_effect as a function instead of a list
    mock_library.search.side_effect = mock_search

    # Setup mock playlist creation
    mock_server.return_value.createPlaylist.return_value = MagicMock(title="New Playlist")

    # Initialize plex service
    plex_service.initialize()
    plex_service._music_library = mock_library
    plex_service._server = mock_server.return_value

    # Test playlist creation
    track_recommendations = [{"artist": "Artist1", "title": "Track1"}]

    playlist = plex_service.create_curated_playlist("New Playlist", track_recommendations)

    assert playlist.title == "New Playlist"
    mock_server.return_value.createPlaylist.assert_called_once()


def test_create_curated_playlist_no_matches(plex_service, mock_plex_server):
    """Test playlist creation with no matching tracks."""
    mock_server, mock_library = mock_plex_server

    # Setup empty search results
    mock_library.search.return_value = []

    # Initialize plex service
    plex_service.initialize()
    plex_service._music_library = mock_library
    plex_service._server = mock_server.return_value

    # Test playlist creation with no matches
    track_recommendations = [{"artist": "NonexistentArtist", "title": "NonexistentTrack"}]

    with pytest.raises(ValueError, match="No tracks could be matched from recommendations"):
        plex_service.create_curated_playlist("New Playlist", track_recommendations)


def test_fuzzy_track_matching(plex_service, mock_plex_server):
    """Test fuzzy matching of track titles."""
    mock_server, mock_library = mock_plex_server

    # Setup mock track
    track1 = MagicMock()
    track1.title = "Track One (Live Version)"
    track1.artist.return_value = MagicMock(title="Artist1")

    # Setup mock album
    album = MagicMock()
    album.tracks.return_value = [track1]

    # Create artist with mock albums
    search_result_artist = MagicMock()
    search_result_artist.title = "Artist1"
    search_result_artist.genres = []
    search_result_artist.albums.return_value = [album]

    # Setup mock searches to handle both artist and track searches
    def mock_search(*args, **kwargs):  # pylint: disable=unused-argument
        if kwargs.get("libtype") == "artist":
            return [search_result_artist]
        if kwargs.get("libtype") == "track":
            return [track1]
        return []

    mock_library.search.side_effect = mock_search

    # Setup mock playlist creation
    mock_server.return_value.createPlaylist.return_value = MagicMock(title="New Playlist")

    # Initialize plex service
    plex_service.initialize()
    plex_service._music_library = mock_library
    plex_service._server = mock_server.return_value

    # Test playlist creation with fuzzy matching
    track_recommendations = [{"artist": "Artist1", "title": "Track One"}]

    playlist = plex_service.create_curated_playlist("New Playlist", track_recommendations)

    assert playlist is not None
    mock_server.return_value.createPlaylist.assert_called_once()


def test_refresh_cache_library_changed(plex_service, mock_plex_server):
    """Test refresh_cache when library has been updated."""
    _, mock_library = mock_plex_server

    # Setup initial state with artists
    artist1 = Mock(ratingKey="1", title="Artist1", genres=[])
    artist2 = Mock(ratingKey="2", title="Artist2", genres=[])

    def mock_search(*args, **kwargs):  # pylint: disable=unused-argument
        libtype = kwargs.get("libtype")
        if libtype == "artist":
            return [artist1, artist2]
        if libtype == "album":
            return [Mock(), Mock(), Mock()]  # 3 albums
        if libtype == "track":
            return [Mock()] * 10  # 10 tracks
        return []

    mock_library.search.side_effect = mock_search
    mock_library.updatedAt = "2024-01-01 10:00:00"

    # Initialize service
    plex_service.initialize()
    assert plex_service._library_updated_at == "2024-01-01 10:00:00"

    # Simulate library update
    mock_library.updatedAt = "2024-01-01 12:00:00"

    # Test refresh
    result = plex_service.refresh_cache()

    assert result is True
    assert plex_service._library_updated_at == "2024-01-01 12:00:00"
    mock_library.reload.assert_called_once()


def test_refresh_cache_library_unchanged(plex_service, mock_plex_server):
    """Test refresh_cache when library has not changed."""
    _, mock_library = mock_plex_server

    # Setup initial state
    artist1 = Mock(ratingKey="1", title="Artist1", genres=[])
    mock_library.search.return_value = [artist1]
    mock_library.updatedAt = "2024-01-01 10:00:00"

    # Initialize service
    plex_service.initialize()

    # Test refresh with same updatedAt
    result = plex_service.refresh_cache()

    assert result is False
    assert plex_service._library_updated_at == "2024-01-01 10:00:00"
    mock_library.reload.assert_called_once()


def test_refresh_cache_no_library(plex_service):
    """Test refresh_cache when music library is not initialized."""
    # Don't initialize - _music_library is None
    result = plex_service.refresh_cache()

    assert result is False


def test_get_library_stats(plex_service, mock_plex_server):
    """Test get_library_stats returns cached stats."""
    _, mock_library = mock_plex_server

    # Setup mock search results
    artist1 = Mock(ratingKey="1", title="Artist1", genres=[])
    artist2 = Mock(ratingKey="2", title="Artist2", genres=[])

    def mock_search(*args, **kwargs):  # pylint: disable=unused-argument
        libtype = kwargs.get("libtype")
        if libtype == "artist":
            return [artist1, artist2]
        if libtype == "album":
            return [Mock()] * 5
        if libtype == "track":
            return [Mock()] * 50
        return []

    mock_library.search.side_effect = mock_search
    mock_library.updatedAt = "2024-01-01 10:00:00"

    # Initialize service
    plex_service.initialize()

    # Get stats
    stats = plex_service.get_library_stats()

    assert stats["artists"] == 2
    assert stats["albums"] == 5
    assert stats["tracks"] == 50


def test_get_library_stats_no_cache(plex_service):
    """Test get_library_stats returns zeros when cache is empty."""
    stats = plex_service.get_library_stats()

    assert stats == {"artists": 0, "albums": 0, "tracks": 0}
