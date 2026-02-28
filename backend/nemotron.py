"""
AI client that talks to NVIDIA NIM (OpenAI-compatible API) to generate
dungeon blueprints via the Nemotron 70B-Instruct model.

The single public entry point is :func:`generate_blueprint`, which sends a
structured prompt to the model and returns a validated :class:`Blueprint`.

A :func:`get_fallback_blueprint` helper is provided for callers that need a
safe default when the AI request fails.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from backend.blueprint import (
    Blueprint,
    BlockPlacement,
    Corridor,
    LootChest,
    MobSpawn,
    Room,
)
from backend.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI-compatible client pointed at NVIDIA NIM
# ---------------------------------------------------------------------------
_client = AsyncOpenAI(
    base_url=settings.nim_base_url,
    api_key=settings.nim_api_key,
)

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are NemoCraft Architect, an expert Minecraft dungeon designer.

Your task is to produce a **dungeon blueprint** as a single JSON object that
conforms EXACTLY to the JSON schema below.

## JSON Schema

```json
{json.dumps(Blueprint.model_json_schema(), indent=2)}
```

## Field reference

### Blueprint (top-level)
- **name** (str): A short, evocative name for the dungeon (e.g. "Crypt of Shadows").
- **palette** (str): The visual theme keyword (e.g. "stone", "nether", "deepslate").
- **rooms** (list[Room]): One or more rooms.  Must contain at least one room.
- **corridors** (list[Corridor]): Passages connecting rooms.  When there are
  N rooms (N > 1) there must be exactly N-1 corridors.  For a single room,
  this should be an empty list.

### Room
- **name** (str): Descriptive room name (e.g. "Grand Hall").
- **width** (int, 5-25): X-axis size in blocks.
- **height** (int, 4-15): Y-axis size in blocks.
- **depth** (int, 5-25): Z-axis size in blocks.
- **shell_block** (str): Block ID for the walls.
- **floor_block** (str): Block ID for the floor.
- **ceiling_block** (str): Block ID for the ceiling.
- **details** (list[BlockPlacement]): Decorative blocks placed inside the room.
  Coordinates must be *within* the room dimensions (0 <= x < width, 0 <= y < height, 0 <= z < depth).
- **mobs** (list[MobSpawn]): Hostile mobs to spawn in the room.
  Coordinates must be within the room floor area.
- **loot_chests** (list[LootChest]): Chests with loot placed on the floor.
  Coordinates must be within the room floor area.

### BlockPlacement
- **block** (str): A valid Minecraft 1.20.1 block ID with "minecraft:" prefix.
- **x**, **y**, **z** (int): Position inside the room.

### MobSpawn
- **entity** (str): A valid Minecraft 1.20.1 entity ID with "minecraft:" prefix.
- **x**, **y**, **z** (int): Spawn position inside the room.
- **count** (int, >=1): How many of this mob to spawn.

### LootChest
- **x**, **y**, **z** (int): Chest position inside the room.
- **items** (list[str]): Valid Minecraft 1.20.1 item IDs with "minecraft:" prefix.

### Corridor
- **width** (int, 2-5): Corridor width in blocks.
- **height** (int, 3-5): Corridor height in blocks.
- **length** (int, 3-15): Corridor length in blocks.
- **block** (str): Block ID for the corridor walls.

## Critical rules

1. **All block, entity, and item IDs MUST use the `minecraft:` prefix** (e.g.
   `"minecraft:stone_bricks"`, `"minecraft:zombie"`, `"minecraft:diamond_sword"`).
2. Respect every numeric constraint listed above — out-of-range values will
   cause a validation error.
3. Coordinates for details, mobs, and loot_chests must stay within the room
   they belong to.
4. Output **only** the JSON object — no markdown fences, no commentary.
"""


def _build_user_prompt(
    prompt: str,
    palette: str,
    narrative_context: dict[str, Any] | None,
) -> str:
    """Assemble the user message sent to the model."""
    parts: list[str] = []

    parts.append(f"Design a Minecraft dungeon with the **{palette}** block palette.")
    parts.append(f"Player request: {prompt}")

    if narrative_context:
        ctx_lines: list[str] = []
        for key, value in narrative_context.items():
            ctx_lines.append(f"- {key}: {value}")
        parts.append("Narrative context:\n" + "\n".join(ctx_lines))

    parts.append(
        "Return the dungeon blueprint as a JSON object that follows the schema "
        "provided in the system prompt."
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

async def generate_blueprint(
    prompt: str,
    palette: str = "stone",
    narrative_context: dict | None = None,
) -> Blueprint:
    """Call NVIDIA NIM to generate a dungeon blueprint.

    Parameters
    ----------
    prompt:
        Free-form player request describing the desired dungeon.
    palette:
        Visual theme keyword (e.g. "stone", "nether", "deepslate").
    narrative_context:
        Optional dictionary of extra context (story beats, difficulty, etc.)
        that will be included in the prompt sent to the model.

    Returns
    -------
    Blueprint
        A fully-validated dungeon blueprint.

    Raises
    ------
    openai.APIError
        If the NVIDIA NIM API call fails.
    pydantic.ValidationError
        If the model output does not pass Blueprint validation.
    """
    user_message = _build_user_prompt(prompt, palette, narrative_context)

    logger.info("Sending blueprint generation request to NIM (%s)", settings.nim_model)
    logger.debug("User prompt: %s", user_message)

    response = await _client.chat.completions.create(
        model=settings.nim_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        top_p=0.95,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content
    logger.debug("Raw NIM response: %s", raw_content)

    blueprint = Blueprint.model_validate_json(raw_content)
    # Ensure the palette field matches the requested palette
    blueprint.palette = palette

    logger.info(
        "Blueprint '%s' generated: %d room(s), %d corridor(s)",
        blueprint.name,
        len(blueprint.rooms),
        len(blueprint.corridors),
    )
    return blueprint


# ---------------------------------------------------------------------------
# Fallback blueprint
# ---------------------------------------------------------------------------

def get_fallback_blueprint(palette: str = "stone") -> Blueprint:
    """Return a safe, hardcoded single-room dungeon.

    Used as a fallback when :func:`generate_blueprint` fails for any reason.
    The room contains 2 zombies, 1 skeleton, and a loot chest with basic gear.
    """
    return Blueprint(
        name="Emergency Vault",
        palette=palette,
        rooms=[
            Room(
                name="Vault Chamber",
                width=10,
                height=6,
                depth=10,
                shell_block="minecraft:stone_bricks",
                floor_block="minecraft:cobblestone",
                ceiling_block="minecraft:stone_bricks",
                details=[
                    BlockPlacement(block="minecraft:cobweb", x=1, y=3, z=1),
                    BlockPlacement(block="minecraft:cobweb", x=8, y=3, z=8),
                    BlockPlacement(block="minecraft:lantern", x=5, y=5, z=5),
                    BlockPlacement(block="minecraft:chain", x=5, y=4, z=5),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:zombie", x=2, y=1, z=3, count=1),
                    MobSpawn(entity="minecraft:zombie", x=7, y=1, z=6, count=1),
                    MobSpawn(entity="minecraft:skeleton", x=5, y=1, z=8, count=1),
                ],
                loot_chests=[
                    LootChest(
                        x=5,
                        y=1,
                        z=1,
                        items=[
                            "minecraft:iron_sword",
                            "minecraft:bread",
                            "minecraft:iron_ingot",
                            "minecraft:golden_apple",
                        ],
                    ),
                ],
            ),
        ],
        corridors=[],
    )
