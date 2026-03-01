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
from backend.registries import VALID_BLOCK_IDS, VALID_ENTITY_IDS, VALID_ITEM_IDS

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
You are NemoCraft Architect, an expert Minecraft dungeon designer who creates
UNIQUE, CREATIVE, and VARIED dungeons every time.

Your task is to produce a **dungeon blueprint** as a single JSON object that
conforms EXACTLY to the JSON schema below.

## JSON Schema

```json
{json.dumps(Blueprint.model_json_schema(), indent=2)}
```

## Available block IDs (use ONLY these)
{json.dumps(sorted(list(VALID_BLOCK_IDS)), indent=0)}

## Available entity IDs (use ONLY these)
{json.dumps(sorted(list(VALID_ENTITY_IDS)), indent=0)}

## Available item IDs (use ONLY these for loot chests)
{json.dumps(sorted(list(VALID_ITEM_IDS)), indent=0)}

## Field reference

### Blueprint (top-level)
- **name** (str): A short, evocative name for the dungeon. Be CREATIVE — never reuse names.
- **palette** (str): The visual theme keyword.
- **rooms** (list[Room]): 1-5 rooms. Vary sizes and shapes. Make each room feel distinct.
- **corridors** (list[Corridor]): When N rooms > 1, exactly N-1 corridors. Empty list for 1 room.

### Room
- **name** (str): Unique, evocative name (e.g. "The Whispering Gallery", "Molten Core Chamber").
- **width** (int, 5-25): X-axis size. VARY between rooms — mix small and large.
- **height** (int, 4-15): Y-axis size. VARY — some tall, some claustrophobic.
- **depth** (int, 5-25): Z-axis size. VARY between rooms.
- **shell_block**, **floor_block**, **ceiling_block** (str): Block IDs from the list above.
  USE DIFFERENT blocks for walls, floor, and ceiling! Mix textures creatively.
- **details** (list[BlockPlacement]): **15-40 decorative blocks per room**. This is what
  makes dungeons feel ALIVE. Details are placed as individual blocks INSIDE the hollow room.
  Coordinates: 1 <= x < width-1, 1 <= y < height-1, 1 <= z < depth-1 (inside the walls).
- **mobs** (list[MobSpawn]): 1-5 mobs per room. Match the theme!
  Coordinates must be within the room interior.
- **loot_chests** (list[LootChest]): 0-2 chests per room with 3-8 items each.
  Coordinates within the room interior.

### Corridor
- **width** (int, 2-5), **height** (int, 3-5), **length** (int, 3-15)
- **block** (str): Block ID for walls. Should match the dungeon theme.

## ARCHITECTURAL DESIGN GUIDELINES — EXTREMELY IMPORTANT

The details list is where you create the dungeon's SOUL. Each room should feel like
a hand-crafted Minecraft build, not an empty box. Use these patterns:

### Structural features (build with shell_block or contrasting blocks)
- **Pillars**: Place columns of blocks from floor to ceiling at regular intervals.
  Example: 4 pillars at corners of a room → place block at (3,1,3), (3,2,3), (3,3,3), (3,4,3) for one pillar.
- **Raised platform / stage**: Fill a section of floor with blocks at y=1 to create elevation.
- **Sunken pit**: Place air or different blocks to suggest a lower area.
- **Archways**: Place blocks in an arch pattern along walls.
- **Walls / partitions**: Create internal dividing walls using blocks.

### Atmospheric details
- **Lighting**: Place lanterns, soul_lanterns, torches, campfires, soul_campfires,
  redstone_lamps, sea_lanterns, end_rods, candles, jack_o_lanterns at varied positions.
  Hang lanterns from ceiling (high y), place torches on walls, campfires on floor.
- **Chains**: Hang from ceiling — place at (x, height-2, z) and (x, height-3, z).
- **Cobwebs**: Scatter in corners and near ceiling for abandoned feel.
- **Iron bars**: Create jail cells, cages, or barriers.
- **Skulls / heads**: Place skeleton_skull, zombie_head, creeper_head on walls for horror.
- **Spawners**: Place minecraft:spawner blocks for spawner-themed rooms.
- **Bookshelves**: Create library rooms with walls of bookshelves.

### Water / lava features
- **Lava channels**: Place lava blocks in trenches (y=1 level) for nether themes.
- **Water pools**: Place water blocks at floor level for ocean themes.
- **Magma floors**: Mix magma_block into floors for danger zones.

### Example: A well-designed 15x8x15 throne room might have:
- 4 pillars (4 blocks tall each = 16 detail blocks)
- 6 lanterns hanging from chains (12 blocks)
- A raised throne platform (4 blocks of stone at one end)
- Cobwebs in 2 corners (2 blocks)
- Iron bars creating a cage/display (4 blocks)
- Skulls on pedestals (2 blocks)
= ~40 detail blocks total

### Key rules for good design:
1. **ALWAYS place 15+ details per room.** Empty rooms are BORING.
2. **Build vertically** — use the full height with pillars, hanging chains, etc.
3. **Create focal points** — every room needs something interesting to look at.
4. **Use contrasting materials** — don't use the same block for everything.
5. **Match the theme** — nether rooms get soul_fire, lava, chains. Ocean gets sea_lanterns, prismarine.

## Critical rules

1. **All IDs MUST come from the lists above.** Using any ID not in those lists will crash.
2. Respect every numeric constraint — out-of-range values cause validation errors.
3. Detail/mob/chest coordinates must stay INSIDE the room (not on the walls).
   Valid range: 1 <= x <= width-2, 1 <= y <= height-2, 1 <= z <= depth-2.
4. Output **only** the JSON object — no markdown fences, no commentary.
"""


def _build_user_prompt(
    prompt: str,
    palette: str,
    narrative_context: dict[str, Any] | None,
) -> str:
    """Assemble the user message sent to the model."""
    parts: list[str] = []

    parts.append(f"Design a UNIQUE Minecraft dungeon with the **{palette}** theme.")
    parts.append(f'Player request: "{prompt}"')
    parts.append(
        "IMPORTANT DESIGN REQUIREMENTS:\n"
        "- Create 2-4 rooms with VARIED sizes (mix large 15x10x15 and small 7x5x7).\n"
        "- Each room MUST have 15-40 detail blocks. Details are what make rooms interesting!\n"
        "- Build PILLARS using columns of blocks (e.g. 4 blocks stacked vertically = 1 pillar).\n"
        "- Hang CHAINS and LANTERNS from ceilings at high y values.\n"
        "- Add LAVA, WATER, or CAMPFIRES at floor level for atmosphere.\n"
        "- Place IRON_BARS, COBWEBS, and SKULLS for decoration.\n"
        "- Use the full height of each room — don't leave the upper space empty.\n"
        "- Make each room architecturally distinct with a clear theme and focal point."
    )

    if narrative_context:
        ctx_lines: list[str] = []
        for key, value in narrative_context.items():
            if key.startswith("karma_"):
                continue  # handled separately below
            ctx_lines.append(f"- {key}: {value}")
        parts.append("Narrative context:\n" + "\n".join(ctx_lines))

        # Add karma alignment section when karma is non-neutral
        karma_tier = narrative_context.get("karma_tier", "neutral")
        karma_narrative = narrative_context.get("karma_narrative", "")
        karma_mood = narrative_context.get("karma_mood", "")
        karma_palette = narrative_context.get("karma_palette", "")
        if karma_tier != "neutral" and karma_narrative:
            karma_section = (
                f"## KARMA ALIGNMENT\n"
                f"- Tier: {karma_tier}\n"
                f"- Mood: {karma_mood}\n"
                f"- Palette: {karma_palette}\n"
                f"- {karma_narrative}\n"
                f"\n"
                f"The dungeon name, room names, block choices, and mob selections "
                f"MUST reflect the {karma_tier} karma alignment. "
            )
            if karma_tier in ("abyssal", "dark", "shadowed"):
                karma_section += (
                    "Use dark, ominous, corrupted themes. "
                    "Names should evoke dread, punishment, or decay."
                )
            elif karma_tier in ("blessed", "sacred", "celestial"):
                karma_section += (
                    "Use light, holy, ethereal themes. "
                    "Names should evoke divinity, hope, or transcendence."
                )
            parts.append(karma_section)

    parts.append(
        "Return the dungeon blueprint as a JSON object that follows the schema "
        "provided in the system prompt. Use ONLY block/entity/item IDs from the "
        "provided lists."
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Blueprint sanitizer — fix invalid IDs instead of crashing
# ---------------------------------------------------------------------------

_DEFAULT_BLOCK = "minecraft:stone_bricks"
_DEFAULT_ENTITY = "minecraft:zombie"


def _sanitize_blueprint(data: dict) -> None:
    """Clean up a raw blueprint dict in-place, replacing invalid IDs with safe defaults.

    This allows the AI's creative dungeon design to be preserved even when it
    uses a few IDs outside our registry.
    """
    # Fix room blocks and contents
    for room in data.get("rooms", []):
        # Fix shell/floor/ceiling blocks
        for key in ("shell_block", "floor_block", "ceiling_block"):
            if room.get(key) and room[key] not in VALID_BLOCK_IDS:
                logger.warning("Replacing invalid block '%s' with '%s'", room[key], _DEFAULT_BLOCK)
                room[key] = _DEFAULT_BLOCK

        # Fix detail blocks
        for detail in room.get("details", []):
            if detail.get("block") and detail["block"] not in VALID_BLOCK_IDS:
                logger.warning("Replacing invalid detail block '%s' with '%s'", detail["block"], _DEFAULT_BLOCK)
                detail["block"] = _DEFAULT_BLOCK

        # Fix mob entities
        for mob in room.get("mobs", []):
            if mob.get("entity") and mob["entity"] not in VALID_ENTITY_IDS:
                logger.warning("Replacing invalid entity '%s' with '%s'", mob["entity"], _DEFAULT_ENTITY)
                mob["entity"] = _DEFAULT_ENTITY

        # Fix loot chest items — remove invalid ones instead of replacing
        for chest in room.get("loot_chests", []):
            if "items" in chest:
                original = chest["items"]
                cleaned = [item for item in original if item in VALID_ITEM_IDS]
                removed = [item for item in original if item not in VALID_ITEM_IDS]
                if removed:
                    logger.warning("Removed invalid items from chest: %s", removed)
                # Ensure at least one item remains
                if not cleaned:
                    cleaned = ["minecraft:iron_sword"]
                chest["items"] = cleaned

        # Clamp room dimensions
        if "width" in room:
            room["width"] = max(5, min(25, room["width"]))
        if "height" in room:
            room["height"] = max(4, min(15, room["height"]))
        if "depth" in room:
            room["depth"] = max(5, min(25, room["depth"]))

    # Fix corridor blocks
    for corridor in data.get("corridors", []):
        if corridor.get("block") and corridor["block"] not in VALID_BLOCK_IDS:
            logger.warning("Replacing invalid corridor block '%s' with '%s'", corridor["block"], _DEFAULT_BLOCK)
            corridor["block"] = _DEFAULT_BLOCK
        if "width" in corridor:
            corridor["width"] = max(2, min(5, corridor["width"]))
        if "height" in corridor:
            corridor["height"] = max(3, min(5, corridor["height"]))
        if "length" in corridor:
            corridor["length"] = max(3, min(15, corridor["length"]))

# ---------------------------------------------------------------------------
# JSON repair for truncated AI responses
# ---------------------------------------------------------------------------


def _repair_json(raw: str) -> dict:
    """Attempt to repair truncated JSON from the AI.

    When the response hits the token limit, the JSON gets cut off mid-way.
    This function tries to close unclosed brackets/braces to make it parseable,
    then trims invalid trailing entries.
    """
    # Strip any markdown fences the AI might add
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    # Try progressively removing trailing characters until we can close brackets
    for trim in range(0, min(1500, len(text))):
        attempt = text[:len(text) - trim] if trim > 0 else text
        attempt = attempt.rstrip()

        # Strip trailing commas or colons to avoid {"key":} or {"key": "val",}
        while attempt and attempt[-1] in (',', ':'):
            attempt = attempt[:-1].rstrip()

        # Parse string safely using a stack
        stack = []
        in_string = False
        escape = False
        for char in attempt:
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char in "{[":
                    stack.append(char)
                elif char in "}]":
                    if stack:
                        stack.pop()

        close_suffix = ""
        if in_string:
            close_suffix += '"'
        
        for char in reversed(stack):
            if char == "{":
                close_suffix += "}"
            elif char == "[":
                close_suffix += "]"

        try:
            data = json.loads(attempt + close_suffix)
            logger.info("JSON repair succeeded (trimmed %d chars)", trim)

            # Ensure corridors count = rooms - 1
            if "rooms" in data and "corridors" in data:
                n_rooms = len(data["rooms"])
                needed = max(0, n_rooms - 1)
                data["corridors"] = data["corridors"][:needed]
                # If we lost corridors, pad with defaults
                while len(data["corridors"]) < needed:
                    data["corridors"].append({
                        "width": 3, "height": 4, "length": 5,
                        "block": "minecraft:stone_bricks",
                    })

            return data
        except (json.JSONDecodeError, ValueError):
            continue

    raise ValueError("Could not repair truncated JSON response from AI")


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
        temperature=0.8,
        top_p=0.95,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content
    logger.debug("Raw NIM response: %s", raw_content)

    # Try to parse the JSON — repair if truncated by token limit
    try:
        raw_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed (%s), attempting repair...", e)
        raw_data = _repair_json(raw_content)

    # Clean up the raw JSON before validation — fix invalid IDs instead of crashing
    _sanitize_blueprint(raw_data)

    blueprint = Blueprint.model_validate(raw_data)
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
