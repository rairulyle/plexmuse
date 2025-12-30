"""
Plex Service with artist caching and optimized album loading.
"""

import logging
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from plexapi.server import PlexServer

from app.models import Artist

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """Normalize track title for better matching by removing common variations"""
    # Convert to lowercase
    title = title.lower()
    # Remove common suffixes in parentheses
    if "(" in title:
        title = title.split("(")[0].strip()
    # Remove special characters but preserve spaces
    title = title.replace("'", "").replace(",", " ").replace(".", " ")
    # Normalize whitespace
    return " ".join(word for word in title.split() if word)


def find_best_track_match(tracks, target_title, threshold=0.85):
    """
    Find best matching track using fuzzy string matching.

    Args:
        tracks: List of track objects from Plex
        target_title: Title to match against
        threshold: Minimum similarity score (0-1) to consider a match

    Returns:
        Tuple of (best_match, score) or (None, 0) if no match found
    """

    target_normalized = normalize_title(target_title)
    best_match = None
    best_score = 0

    for track in tracks:
        track_normalized = normalize_title(track.title)

        # Calculate similarity on normalized titles
        score = SequenceMatcher(None, track_normalized, target_normalized).ratio()

        # If exact match found after normalization, return immediately
        if score == 1.0:
            return track, 1.0

        if score > best_score and score >= threshold:
            best_score = score
            best_match = track

    return best_match, best_score


class PlexService:
    """
    A service class for interacting with the Plex API with artist caching.
    """

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self._server: Optional[PlexServer] = None
        self.machine_identifier: Optional[str] = None
        self._music_library = None

        # Only cache artists
        self._artists_cache: Dict[str, Artist] = {}  # key: artist_id -> Artist
        self._stats_cache: Optional[Dict[str, int]] = None
        self._library_updated_at: Optional[str] = None

    def get_cache_size(self) -> int:
        """Get the number of artists in the cache"""
        return len(self._artists_cache)

    def get_library_stats(self) -> dict:
        """Get library statistics (artists, albums, tracks) from cache"""
        if self._stats_cache:
            return self._stats_cache
        return {"artists": 0, "albums": 0, "tracks": 0}

    def initialize(self):
        """Initialize artist cache"""
        logger.info("Initializing PlexService artist cache...")
        try:
            self._server = PlexServer(self.base_url, self.token)
            self.machine_identifier = self._server.machineIdentifier

            self._music_library = self._server.library.section("Music")

            # Load all artists
            artists = self._music_library.search(libtype="artist")
            for artist in artists:
                artist_id = str(artist.ratingKey)
                self._artists_cache[artist_id] = Artist(
                    id=artist_id, name=artist.title, genres=[genre.tag for genre in getattr(artist, "genres", [])]
                )

            # Cache library stats and updatedAt timestamp
            self._stats_cache = {
                "artists": len(self._artists_cache),
                "albums": len(self._music_library.search(libtype="album")),
                "tracks": len(self._music_library.search(libtype="track")),
            }
            self._library_updated_at = str(self._music_library.updatedAt) if self._music_library.updatedAt else None

            logger.info(
                "Cached %d artists, %d albums, %d tracks (updatedAt: %s)",
                self._stats_cache["artists"],
                self._stats_cache["albums"],
                self._stats_cache["tracks"],
                self._library_updated_at,
            )

        except Exception as e:
            logger.error("Failed to initialize Plex cache: %s", str(e))
            raise

    def refresh_cache(self) -> bool:
        """Refresh cache if library has been updated. Returns True if cache was refreshed."""
        if not self._music_library:
            return False

        # Reload the library section to get fresh updatedAt
        self._music_library.reload()
        current_updated_at = str(self._music_library.updatedAt) if self._music_library.updatedAt else None

        if current_updated_at != self._library_updated_at:
            logger.info(
                "Library updated (was: %s, now: %s). Refreshing cache...",
                self._library_updated_at,
                current_updated_at,
            )
            # Clear existing cache
            self._artists_cache.clear()
            self._stats_cache = None

            # Reload artists
            artists = self._music_library.search(libtype="artist")
            for artist in artists:
                artist_id = str(artist.ratingKey)
                self._artists_cache[artist_id] = Artist(
                    id=artist_id, name=artist.title, genres=[genre.tag for genre in getattr(artist, "genres", [])]
                )

            # Reload stats
            self._stats_cache = {
                "artists": len(self._artists_cache),
                "albums": len(self._music_library.search(libtype="album")),
                "tracks": len(self._music_library.search(libtype="track")),
            }
            self._library_updated_at = current_updated_at

            logger.info(
                "Cache refreshed: %d artists, %d albums, %d tracks",
                self._stats_cache["artists"],
                self._stats_cache["albums"],
                self._stats_cache["tracks"],
            )
            return True

        logger.info("Library not changed, cache is up to date")
        return False

    def get_all_artists(self) -> List[Artist]:
        """Get all artists from cache"""
        return list(self._artists_cache.values())

    def get_artists_albums_bulk(self, artist_names: List[str]) -> dict:
        """Get albums for multiple artists in one go"""
        if not self._server:
            self._server = PlexServer(self.base_url, self.token)

        result = {}
        # Find all matching artists first
        artist_objects = []
        for artist_name in artist_names:
            artist_found = None
            # First try cache lookup by name
            for artist in self._artists_cache.values():
                if artist.name.lower() == artist_name.lower():
                    # Found in cache, now get the Plex object
                    matches = self._music_library.search(artist.name, libtype="artist")
                    if matches:
                        artist_found = matches[0]
                        break

            if artist_found:
                artist_objects.append(artist_found)
            else:
                logger.warning("Artist not found: %s", artist_name)

        # Now get all albums in one go
        for artist in artist_objects:
            albums = []
            for album in artist.albums():
                albums.append({"name": album.title, "year": album.year, "track_count": len(album.tracks())})
            result[artist.title] = albums

        return result

    def create_curated_playlist(
        self, name: str, track_recommendations: List[dict]
    ):  # pylint: disable=too-many-locals,too-many-branches
        """Create a playlist with fuzzy track matching"""
        if not self._server:
            self._server = PlexServer(self.base_url, self.token)

        matched_tracks = []
        # Group recommendations by artist for efficiency
        artist_tracks = {}
        for rec in track_recommendations:
            artist_tracks.setdefault(rec["artist"], []).append(rec["title"])

        # Process each artist's tracks in bulk
        for artist_name, track_titles in artist_tracks.items():
            artists = self._music_library.search(artist_name, libtype="artist")
            if not artists:
                logger.warning("Artist not found: %s", artist_name)
                continue

            artist = artists[0]
            # Get all tracks for this artist at once
            all_tracks = []
            for album in artist.albums():
                all_tracks.extend(album.tracks())

            # Match tracks using fuzzy matching
            for title in track_titles:
                track, score = find_best_track_match(all_tracks, title)
                if track:
                    logger.debug("Matched '%s' to '%s' (score: %.2f)", title, track.title, score)
                    matched_tracks.append(track)
                else:
                    # If no match found for artist, try global search
                    global_tracks = self._music_library.search(title, libtype="track")
                    if global_tracks:
                        track, score = find_best_track_match(global_tracks, title, threshold=0.75)
                        if track and track.artist().title.lower() == artist_name.lower():
                            logger.debug("Found track '%s' through global search (score: %.2f)", track.title, score)
                            matched_tracks.append(track)
                        else:
                            logger.warning("No matching track found for: %s by %s", title, artist_name)
                    else:
                        logger.warning("No matching track found for: %s by %s", title, artist_name)

        if not matched_tracks:
            raise ValueError("No tracks could be matched from recommendations")

        playlist = self._server.createPlaylist(name, items=matched_tracks)
        return playlist
