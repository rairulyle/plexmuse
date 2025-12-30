"""
Plexmuse API with initialization
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.models import Artist, LLMProvider, PlaylistRequest, PlaylistResponse, Track

from .services.llm_service import LLMService
from .services.plex_service import PlexService

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

# Initialize services
plex_service = PlexService(base_url=os.getenv("PLEX_BASE_URL"), token=os.getenv("PLEX_TOKEN"))
llm_service = LLMService()


@asynccontextmanager
async def lifespan(app_context: FastAPI):  # pylint: disable=unused-argument
    """Lifespan event handler for service initialization and cleanup"""
    # Initialize services on startup
    plex_service.initialize()
    yield
    # Cleanup on shutdown (if needed in the future)


app = FastAPI(
    title="Plexmuse API",
    description="API for generating AI-powered playlists from your Plex music library",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """Serve the index.html file with Plex configuration injected"""
    plex_base_url = os.getenv("PLEX_BASE_URL")
    plex_token = os.getenv("PLEX_TOKEN")

    with open("static/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    # Inject Plex configuration before closing body tag
    script_tag = f"""<script>
        window.plexBaseUrl = "{plex_base_url}";
        window.plexToken = "{plex_token}";
    </script>"""
    html_content = html_content.replace("</body>", f"{script_tag}</body>")

    return HTMLResponse(content=html_content)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "cache_size": plex_service.get_cache_size()}


@app.get("/artists", response_model=List[Artist])
async def get_artists():
    """Get all artists from the Plex music library"""
    return plex_service.get_all_artists()


def _get_all_providers() -> List[LLMProvider]:
    """Get all provider definitions (internal use)"""
    providers = []

    # Check for OpenAI API key
    if os.getenv("OPENAI_API_KEY"):
        providers.extend([
            LLMProvider(
                id="openai-gpt5",
                name="GPT 5",
                model="openai/gpt-5",
                description="Deep music knowledge for cohesive playlists. Capacity: ~6k artists or ~8k albums.",
                temperature=1.0,
            ),
            LLMProvider(
                id="openai-gpt5-mini",
                name="GPT 5 mini",
                model="openai/gpt-5-mini",
                description="Balanced genre-aware curation. Capacity: ~6k artists or ~8k albums.",
                temperature=1.0,
            ),
            LLMProvider(
                id="openai-gpt5-nano",
                name="GPT 5 nano",
                model="openai/gpt-5-nano",
                description="Instant playlist generation. Capacity: ~4k artists or ~5k albums.",
                temperature=1.0,
            ),
        ])

    # Check for Anthropic API key
    if os.getenv("ANTHROPIC_API_KEY"):
        providers.extend([
            LLMProvider(
                id="anthropic-sonnet",
                name="Claude Sonnet 4.5",
                model="anthropic/claude-sonnet-4-5-20250929",
                description="Excellent thematic flow and mood transitions. Capacity: ~10k artists or ~13k albums.",
                temperature=0.7,
            ),
            LLMProvider(
                id="anthropic-haiku",
                name="Claude Haiku 3",
                model="anthropic/claude-3-haiku-20240307",
                description="Speedy vibe-matching. Capacity: ~10k artists or ~13k albums.",
                temperature=0.7,
            ),
        ])

    # Check for Gemini API key
    if os.getenv("GEMINI_API_KEY"):
        providers.extend([
            LLMProvider(
                id="gemini-flash",
                name="Gemini Flash",
                model="gemini/gemini-flash-latest",
                description="Fast and powerful for massive libraries. Capacity: ~50k artists or ~65k albums.",
                temperature=1.0,
            )
        ])

    return providers


def _get_temperature_for_model(model: str) -> float:
    """Look up temperature for a model from providers"""
    for provider in _get_all_providers():
        if provider.model == model:
            return provider.temperature
    return 0.7  # Default fallback


@app.get("/providers", response_model=List[LLMProvider])
async def get_providers():
    """Get available LLM providers based on configured API keys"""
    return _get_all_providers()


@app.post("/recommendations", response_model=PlaylistResponse)
async def create_recommendations(request: PlaylistRequest):
    """Create playlist recommendations"""
    try:
        # Get temperature for the selected model
        temperature = _get_temperature_for_model(request.model)

        # Step 1: Get artist recommendations
        artists = plex_service.get_all_artists()
        recommended_artists = llm_service.get_artist_recommendations(
            prompt=request.prompt, artists=artists, model=request.model, temperature=temperature
        )

        # Step 2: Get all recommended artists' albums in one call
        artist_albums = plex_service.get_artists_albums_bulk(recommended_artists)

        # Step 3: Get track recommendations
        track_recommendations = llm_service.get_track_recommendations(
            prompt=request.prompt,
            artist_tracks=artist_albums,
            model=request.model,
            temperature=temperature,
            min_tracks=request.min_tracks,
            max_tracks=request.max_tracks,
        )

        # Step 4: Generate playlist name
        playlist_name = llm_service.generate_playlist_name(
            prompt=request.prompt, model=request.model, temperature=temperature
        )

        # Step 5: Create the playlist
        playlist = plex_service.create_curated_playlist(
            name=playlist_name,
            track_recommendations=track_recommendations,
        )
        return PlaylistResponse(
            name=playlist.title,
            track_count=len(track_recommendations),
            tracks=[Track(artist=rec["artist"], title=rec["title"]) for rec in track_recommendations],
            id=str(playlist.ratingKey) if hasattr(playlist, "ratingKey") else None,
            machine_identifier=plex_service.machine_identifier,
        )
    except Exception as e:
        logger.error("Error creating playlist: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e
