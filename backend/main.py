"""
NemoCraft FastAPI application — all HTTP endpoints for dungeon generation,
player stats ingestion, and automatic generation checks.

Steps 8 + 16 of the NemoCraft build plan.
"""

import logging
import time

from fastapi import FastAPI
from pydantic import BaseModel

from typing import Optional

from backend.config import settings
from backend.blueprint import Blueprint
from backend.nemotron import generate_blueprint, get_fallback_blueprint
from backend.placer import solve_placement
from backend.builder import BuildExecutor
from backend.stats import PlayerProfile
from backend.narrative import NarrativeEngine, NarrativeContext
from backend.quests import QuestEngine, QuestType
from backend.karma import KarmaTier, TIER_PALETTES
from backend.villain import VillainAgent

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


from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    logger.error("Validation error on %s %s", request.method, request.url.path)
    logger.error("Raw body: %s", body.decode(errors='replace'))
    logger.error("Errors: %s", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.post("/api/build")
async def api_build(req: BuildRequest):
    """Full structure generation pipeline: AI blueprint -> placement -> RCON build."""

    # 1. Auto-detect palette if not provided
    palette = req.palette if req.palette else _detect_palette(req.prompt)

    # 2. Build narrative context if player_uuid is provided
    narrative_context: NarrativeContext | None = None
    narrative_engine: NarrativeEngine | None = None
    karma_tier_str = "neutral"
    if req.player_uuid:
        try:
            narrative_engine = NarrativeEngine(data_dir=DATA_DIR)
            narrative_context = narrative_engine.build_context(
                req.player_uuid, req.player_name,
            )
            karma_tier_str = narrative_context.karma_tier
            logger.info(
                "Narrative context built for %s: theme=%s, difficulty=%d, karma=%s",
                req.player_uuid,
                narrative_context.theme,
                narrative_context.difficulty_level,
                karma_tier_str,
            )
            # Karma palette override when no explicit palette requested
            if not req.palette and narrative_context.karma_palette:
                palette = narrative_context.karma_palette
                logger.info("Karma palette override: %s", palette)
        except Exception:
            logger.exception("Failed to build narrative context, proceeding without it")
            narrative_context = None

    # 3. Generate blueprint (with fallback)
    narrative_dict = narrative_context.model_dump() if narrative_context else None
    try:
        blueprint = await generate_blueprint(req.prompt, palette, narrative_dict)
    except Exception:
        logger.exception("AI blueprint generation failed, using fallback")
        # Detect structure type for better fallback
        from backend.nemotron import _detect_structure_type
        structure_type = _detect_structure_type(req.prompt)
        blueprint = get_fallback_blueprint(palette, structure_type)

    # 4. Solve placement
    placed = solve_placement(
        blueprint, int(req.x), int(req.y), int(req.z),
        karma_tier=karma_tier_str,
    )

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
        "structure_type": result.get("structure_type", "dungeon"),
        "message": "Structure built successfully",
    }


@app.post("/api/stats")
async def api_stats(req: StatsRequest):
    """Ingest a player stats snapshot and return karma state."""
    profile = PlayerProfile(req.player_uuid, data_dir=DATA_DIR)
    profile.add_snapshot(req.stats)
    karma_score = profile.get_karma_score()
    karma_tier = profile.get_karma_tier()
    return {
        "status": "ok",
        "karma_score": karma_score,
        "karma_tier": karma_tier.value,
    }


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
    karma_tier_str = "neutral"
    try:
        narrative_context = narrative_engine.build_context(
            req.player_uuid, "Adventurer",
        )
        karma_tier_str = narrative_context.karma_tier
    except Exception:
        logger.exception("Failed to build narrative context for auto-gen")
        narrative_context = None

    # 4. Generate blueprint (with fallback)
    narrative_dict = narrative_context.model_dump() if narrative_context else None

    # Karma palette takes priority, then theme-based palette
    if narrative_context and narrative_context.karma_palette:
        palette = narrative_context.karma_palette
    else:
        palette = narrative_context.theme if narrative_context else "stone"
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
    placed = solve_placement(
        blueprint, int(req.x), int(req.y), int(req.z),
        karma_tier=karma_tier_str,
    )

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


# ---------------------------------------------------------------------------
# Quest request models
# ---------------------------------------------------------------------------


class QuestGenerateRequest(BaseModel):
    player_uuid: str
    player_name: str = "Adventurer"
    x: float = 0
    y: float = 64
    z: float = 0


class QuestAcceptRequest(BaseModel):
    player_uuid: str
    quest_id: str


class QuestProgressRequest(BaseModel):
    player_uuid: str
    objective_type: str  # kill, explore, collect, build, etc.
    target: str          # entity/item/location ID
    count: int = 1


class QuestCompleteRequest(BaseModel):
    player_uuid: str
    quest_id: str
    x: float = 0
    y: float = 64
    z: float = 0


# ---------------------------------------------------------------------------
# Quest endpoints
# ---------------------------------------------------------------------------


@app.post("/api/quests/generate")
async def api_quests_generate(req: QuestGenerateRequest):
    """Generate new quests for a player using Nemotron.

    Creates 1-3 quests based on the player's stats, playstyle, and narrative
    history. Each quest leads to a specific structure type (dungeon, village,
    temple, etc.) with objectives and rewards.
    """
    quest_engine = QuestEngine(data_dir=DATA_DIR)

    try:
        quests = await quest_engine.generate_quests(
            player_uuid=req.player_uuid,
            player_name=req.player_name,
            player_x=req.x,
            player_y=req.y,
            player_z=req.z,
        )
    except Exception:
        logger.exception("Quest generation failed")
        return {"quests": [], "message": "Quest generation failed"}

    return {
        "quests": [q.model_dump() for q in quests],
        "message": f"Generated {len(quests)} new quest(s)",
    }


@app.get("/api/quests/{player_uuid}")
async def api_quests_list(player_uuid: str):
    """Get all active/available quests for a player."""
    quest_engine = QuestEngine(data_dir=DATA_DIR)
    quests = quest_engine.get_active_quests(player_uuid)

    return {
        "quests": [q.model_dump() for q in quests],
        "count": len(quests),
    }


@app.post("/api/quests/accept")
async def api_quests_accept(req: QuestAcceptRequest):
    """Accept an available quest, marking it as active."""
    quest_engine = QuestEngine(data_dir=DATA_DIR)
    quest = quest_engine.accept_quest(req.player_uuid, req.quest_id)

    if quest is None:
        return {"status": "error", "message": "Quest not found or already accepted"}

    return {
        "status": "ok",
        "quest": quest.model_dump(),
        "message": f"Quest accepted: {quest.name}",
    }


@app.post("/api/quests/progress")
async def api_quests_progress(req: QuestProgressRequest):
    """Update quest objective progress (e.g. player killed a mob, collected an item).

    Automatically completes quests when all objectives are met.
    """
    quest_engine = QuestEngine(data_dir=DATA_DIR)

    try:
        quest_type = QuestType(req.objective_type)
    except ValueError:
        return {"status": "error", "message": f"Invalid objective type: {req.objective_type}"}

    completed = quest_engine.update_progress(
        player_uuid=req.player_uuid,
        objective_type=quest_type,
        target=req.target,
        count=req.count,
    )

    return {
        "status": "ok",
        "completed_quests": [q.model_dump() for q in completed],
        "message": f"{len(completed)} quest(s) completed" if completed else "Progress updated",
    }


@app.post("/api/quests/complete")
async def api_quests_complete(req: QuestCompleteRequest):
    """Complete a quest and trigger its reward structure generation.

    If the quest has a destination_prompt, this builds the quest destination
    structure at the player's location using the full generation pipeline.
    """
    quest_engine = QuestEngine(data_dir=DATA_DIR)
    log = quest_engine.load_quest_log(req.player_uuid)

    # Find the completed quest
    target_quest = None
    for quest in log.completed_quests:
        if quest.quest_id == req.quest_id:
            target_quest = quest
            break

    if target_quest is None:
        # Also check active quests (might have all objectives done)
        for quest in log.active_quests:
            if quest.quest_id == req.quest_id and quest.all_objectives_complete:
                target_quest = quest
                break

    if target_quest is None:
        return {"status": "error", "message": "Quest not found or not completed"}

    result = {
        "status": "ok",
        "quest": target_quest.model_dump(),
        "rewards": target_quest.rewards.model_dump(),
    }

    # Build the quest reward structure if there's a structure prompt
    structure_prompt = target_quest.rewards.structure_prompt or target_quest.destination_prompt
    if structure_prompt:
        try:
            palette = _detect_palette(structure_prompt)
            blueprint = await generate_blueprint(structure_prompt, palette)
            placed = solve_placement(blueprint, int(req.x), int(req.y), int(req.z))
            executor = BuildExecutor()
            build_result = await executor.build(placed)
            result["structure_built"] = {
                "name": build_result["name"],
                "room_count": build_result["room_count"],
            }
            result["message"] = (
                f"Quest complete! Built '{build_result['name']}' as your reward destination."
            )
        except Exception:
            logger.exception("Failed to build quest reward structure")
            result["message"] = "Quest complete! (Structure build failed)"
    else:
        result["message"] = f"Quest complete: {target_quest.name}"

    return result


# ---------------------------------------------------------------------------
# Karma endpoint
# ---------------------------------------------------------------------------


@app.get("/api/karma/{player_uuid}")
async def api_karma(player_uuid: str):
    """Debug endpoint: return full karma state for a player."""
    profile = PlayerProfile(player_uuid, data_dir=DATA_DIR)
    karma = profile.karma
    score = profile.get_karma_score()
    tier = profile.get_karma_tier()
    return {
        "player_uuid": player_uuid,
        "karma_score": score,
        "karma_tier": tier.value,
        "dimensions": {
            "violence": round(karma.violence, 2),
            "nature": round(karma.nature, 2),
            "social": round(karma.social, 2),
        },
        "last_updated": karma.last_updated,
    }


# ---------------------------------------------------------------------------
# Villain chatbot request models
# ---------------------------------------------------------------------------


class VillainChatRequest(BaseModel):
    player_uuid: str
    player_name: str = "Player"
    message: str
    x: float = 0
    y: float = 64
    z: float = 0


class VillainEventRequest(BaseModel):
    player_uuid: str
    player_name: str = "Player"
    event_type: str
    event_data: dict = {}
    x: float = 0
    y: float = 64
    z: float = 0


# ---------------------------------------------------------------------------
# Villain endpoints
# ---------------------------------------------------------------------------


@app.get("/api/villain/status")
async def api_villain_status():
    """Check if the villain chatbot is enabled."""
    return {
        "enabled": settings.villain_enabled,
        "name": settings.villain_name,
    }


@app.post("/api/villain/chat")
async def api_villain_chat(req: VillainChatRequest):
    """Player chat routed to the villain agent."""
    if not settings.villain_enabled:
        return {"status": "disabled"}

    agent = VillainAgent(data_dir=DATA_DIR)
    try:
        result = await agent.respond(
            player_uuid=req.player_uuid,
            player_name=req.player_name,
            message=req.message,
            x=req.x,
            y=req.y,
            z=req.z,
        )
    except Exception:
        logger.exception("Villain chat failed")
        return {"status": "error", "message": "Villain agent encountered an error"}

    return {"status": "ok", **result}


@app.post("/api/villain/event")
async def api_villain_event(req: VillainEventRequest):
    """Game event notification routed to the villain agent."""
    if not settings.villain_enabled:
        return {"status": "disabled"}

    agent = VillainAgent(data_dir=DATA_DIR)
    try:
        result = await agent.react_to_event(
            player_uuid=req.player_uuid,
            player_name=req.player_name,
            event_type=req.event_type,
            event_data=req.event_data,
            x=req.x,
            y=req.y,
            z=req.z,
        )
    except Exception:
        logger.exception("Villain event reaction failed")
        return {"status": "error", "message": "Villain event reaction failed"}

    if result is None:
        return {"status": "ok", "reacted": False}

    return {"status": "ok", "reacted": True, **result}
