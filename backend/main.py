"""
NemoCraft FastAPI application — all HTTP endpoints for dungeon generation,
player stats ingestion, and automatic generation checks.

Steps 8 + 16 of the NemoCraft build plan.
"""

import logging
import time

from fastapi import FastAPI
from pydantic import BaseModel

from backend.config import settings
from backend.blueprint import Blueprint
from backend.nemotron import generate_blueprint, get_fallback_blueprint
from backend.placer import solve_placement
from backend.builder import BuildExecutor
from backend.stats import PlayerProfile
from backend.narrative import NarrativeEngine, NarrativeContext

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = "player_data"

# Palette auto-detection keyword map
_PALETTE_KEYWORDS: dict[str, list[str]] = {
    "nether": ["nether", "blaze", "fortress"],
    "deepslate": ["deep", "deepslate", "sculk"],
    "ocean": ["ocean", "prismarine", "guardian"],
    "end": ["end", "purpur", "dragon"],
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="NemoCraft", version="1.0.0")

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class BuildRequest(BaseModel):
    prompt: str
    player_name: str = "Player"
    x: float = 0
    y: float = 64
    z: float = 0
    biome: str = "minecraft:plains"
    palette: str = ""
    player_uuid: str = ""


class StatsRequest(BaseModel):
    player_uuid: str
    stats: dict


class CheckRequest(BaseModel):
    player_uuid: str
    x: float = 0
    y: float = 64
    z: float = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_palette(prompt: str) -> str:
    """Auto-detect a block palette from keywords in the prompt.

    Returns the first matching palette, or ``"stone"`` as the default.
    """
    lower = prompt.lower()
    for palette, keywords in _PALETTE_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return palette
    return "stone"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Simple liveness probe."""
    return {"status": "ok"}


@app.post("/api/build")
async def api_build(req: BuildRequest):
    """Full dungeon generation pipeline: AI blueprint -> placement -> RCON build."""

    # 1. Auto-detect palette if not provided
    palette = req.palette if req.palette else _detect_palette(req.prompt)

    # 2. Build narrative context if player_uuid is provided
    narrative_context: NarrativeContext | None = None
    narrative_engine: NarrativeEngine | None = None
    if req.player_uuid:
        try:
            narrative_engine = NarrativeEngine(data_dir=DATA_DIR)
            narrative_context = narrative_engine.build_context(
                req.player_uuid, req.player_name,
            )
            logger.info(
                "Narrative context built for %s: theme=%s, difficulty=%d",
                req.player_uuid,
                narrative_context.theme,
                narrative_context.difficulty_level,
            )
        except Exception:
            logger.exception("Failed to build narrative context, proceeding without it")
            narrative_context = None

    # 3. Generate blueprint (with fallback)
    narrative_dict = narrative_context.model_dump() if narrative_context else None
    try:
        blueprint = await generate_blueprint(req.prompt, palette, narrative_dict)
    except Exception:
        logger.exception("AI blueprint generation failed, using fallback")
        blueprint = get_fallback_blueprint(palette)

    # 4. Solve placement
    placed = solve_placement(blueprint, int(req.x), int(req.y), int(req.z))

    # 5. Build in-world via RCON
    try:
        executor = BuildExecutor()
        result = await executor.build(placed)
    except Exception as exc:
        logger.exception("Build execution failed")
        return {"error": f"Build failed: {exc}"}

    # 6. Save dungeon record if narrative engine was used
    if req.player_uuid and narrative_engine is not None:
        try:
            narrative_engine.save_dungeon_record(
                req.player_uuid,
                result["name"],
                narrative_context.theme if narrative_context else "unknown",
            )
        except Exception:
            logger.exception("Failed to save dungeon record")

    # 7. Return success
    return {
        "name": result["name"],
        "room_count": result["room_count"],
        "message": "Dungeon built successfully",
    }


@app.post("/api/stats")
async def api_stats(req: StatsRequest):
    """Ingest a player stats snapshot."""
    profile = PlayerProfile(req.player_uuid, data_dir=DATA_DIR)
    profile.add_snapshot(req.stats)
    return {"status": "ok"}


@app.post("/api/check")
async def api_check(req: CheckRequest):
    """Automatic generation check — decides whether to auto-build a dungeon.

    Evaluates player intensity against the configured threshold and enforces
    a cooldown window between successive auto-generated dungeons.
    """

    # 1. Load profile and check intensity
    profile = PlayerProfile(req.player_uuid, data_dir=DATA_DIR)
    intensity = profile.get_intensity()

    if intensity < settings.auto_generate_threshold:
        return {"generate": False, "message": "Activity too low"}

    # 2. Check cooldown via narrative history timestamps
    narrative_engine = NarrativeEngine(data_dir=DATA_DIR)
    history = narrative_engine._load_history(req.player_uuid)

    if history:
        last_entry = history[-1]
        last_timestamp = last_entry.get("timestamp", 0)
        elapsed_minutes = (time.time() - last_timestamp) / 60.0
        if elapsed_minutes < settings.auto_generate_cooldown_minutes:
            return {"generate": False, "message": "Cooldown active"}

    # 3. Should generate — build narrative context
    try:
        narrative_context = narrative_engine.build_context(
            req.player_uuid, "Adventurer",
        )
    except Exception:
        logger.exception("Failed to build narrative context for auto-gen")
        narrative_context = None

    # 4. Generate blueprint (with fallback)
    narrative_dict = narrative_context.model_dump() if narrative_context else None
    palette = narrative_context.theme if narrative_context else "stone"
    # Map narrative themes to palettes
    palette_map = {
        "retribution": "nether",
        "discovery": "stone",
        "invasion": "deepslate",
        "mystery": "end",
    }
    palette = palette_map.get(palette, "stone")

    try:
        blueprint = await generate_blueprint(
            f"Auto-generated dungeon for an active player", palette, narrative_dict,
        )
    except Exception:
        logger.exception("AI blueprint generation failed for auto-gen, using fallback")
        blueprint = get_fallback_blueprint(palette)

    # 5. Place and build
    placed = solve_placement(blueprint, int(req.x), int(req.y), int(req.z))

    try:
        executor = BuildExecutor()
        result = await executor.build(placed)
    except Exception as exc:
        logger.exception("Auto-gen build execution failed")
        return {"generate": False, "message": f"Build failed: {exc}"}

    # 6. Save dungeon record with timestamp for cooldown tracking
    try:
        # Save via the engine's history directly so we can include a timestamp
        record_history = narrative_engine._load_history(req.player_uuid)
        record_history.append({
            "dungeon_name": result["name"],
            "theme": narrative_context.theme if narrative_context else "unknown",
            "timestamp": time.time(),
        })
        narrative_engine._save_history(req.player_uuid, record_history)
    except Exception:
        logger.exception("Failed to save auto-gen dungeon record")

    # 7. Return success
    return {
        "generate": True,
        "message": f"Auto-generated dungeon: {result['name']}",
    }
