"""
AI client that talks to NVIDIA NIM (OpenAI-compatible API) to generate
structure blueprints via the Nemotron 70B-Instruct model.

Supports generating dungeons, villages, castles, towers, temples,
houses, marketplaces, and many other Minecraft structure types.

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
    VALID_STRUCTURE_TYPES,
    VALID_ROOF_TYPES,
    VALID_LAYOUT_TYPES,
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
# Structure type detection
# ---------------------------------------------------------------------------

_STRUCTURE_KEYWORDS: dict[str, list[str]] = {
    "village":      ["village", "settlement", "hamlet", "town", "colony"],
    "castle":       ["castle", "citadel", "stronghold", "keep", "fortress"],
    "tower":        ["tower", "spire", "watchtower", "bell tower", "lookout"],
    "house":        ["house", "cottage", "cabin", "hut", "shack", "home", "dwelling"],
    "temple":       ["temple", "shrine", "sanctuary", "altar", "chapel", "holy"],
    "marketplace":  ["marketplace", "market", "bazaar", "trading post", "shop"],
    "fort":         ["fort", "garrison", "outpost", "barracks", "military"],
    "treehouse":    ["treehouse", "tree house", "treetop", "canopy"],
    "ship":         ["ship", "boat", "galleon", "pirate ship", "vessel", "ark"],
    "ruins":        ["ruins", "ruined", "abandoned", "crumbling", "ancient ruins"],
    "cathedral":    ["cathedral", "basilica", "grand church", "monastery"],
    "mansion":      ["mansion", "manor", "estate", "palace", "grand house"],
    "tavern":       ["tavern", "inn", "pub", "bar", "saloon"],
    "farm":         ["farm", "ranch", "barn", "homestead", "plantation"],
    "lighthouse":   ["lighthouse", "beacon", "watchtower"],
    "bridge":       ["bridge", "overpass", "crossing", "aqueduct"],
    "arena":        ["arena", "colosseum", "stadium", "gladiator", "fighting pit"],
    "library":      ["library", "archives", "study", "academy", "school"],
    "prison":       ["prison", "jail", "dungeon", "cell", "penitentiary"],
    "mine":         ["mine", "mineshaft", "quarry", "excavation"],
    "monument":     ["monument", "statue", "memorial", "obelisk", "pillar"],
}


def _detect_structure_type(prompt: str) -> str:
    """Detect structure type from the user's prompt."""
    lower = prompt.lower()
    for struct_type, keywords in _STRUCTURE_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return struct_type
    return "dungeon"


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are NemoCraft Architect, an expert Minecraft builder who creates
IMPRESSIVE, CREATIVE, and VARIED structures every time.

You can build ANY type of structure: dungeons, villages, castles, towers,
houses, temples, marketplaces, ships, treehouses, farms, and more.

Your task is to produce a **structure blueprint** as a single JSON object that
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

## Structure Types
Valid structure_type values: {json.dumps(sorted(list(VALID_STRUCTURE_TYPES)))}

## Layout Types
Valid layout values: {json.dumps(sorted(list(VALID_LAYOUT_TYPES)))}
- "linear": Buildings connected in a chain (good for dungeons, castles)
- "grid": Buildings in rows/columns (good for villages, farms, marketplaces)
- "circular": Buildings in a ring (good for temples, forts, arenas)
- "cluster": Organic irregular placement (good for ruins, treehouses)
- "single": One standalone building (good for houses, towers, taverns)

## Roof Types
Valid roof_type values: {json.dumps(sorted(list(VALID_ROOF_TYPES)))}
- "peaked": A-frame / triangular roof
- "gable": Rectangular peaked roof with gable ends
- "dome": Rounded dome roof
- "flat": Flat roof / rooftop terrace
- "none": No roof (underground/dungeon rooms)

## Field reference

### Blueprint (top-level)
- **name** (str): A short, evocative name. Be CREATIVE — never reuse names.
- **palette** (str): The visual theme keyword.
- **structure_type** (str): Type of structure being built.
- **layout** (str): How rooms/buildings are arranged spatially.
- **rooms** (list[Room]): 1-5 rooms/buildings. Vary sizes. Make each feel distinct.
- **corridors** (list[Corridor]): When N rooms > 1, exactly N-1 corridors/paths.

### Room (represents a building OR a room within a larger structure)
- **name** (str): Unique, evocative name (e.g. "The Blacksmith's Forge", "Grand Throne Room").
- **width** (int, 5-30): X-axis size. VARY between rooms.
- **height** (int, 4-20): Y-axis size. Taller for towers/cathedrals, shorter for huts.
- **depth** (int, 5-30): Z-axis size. VARY between rooms.
- **shell_block**, **floor_block**, **ceiling_block** (str): Block IDs from the list.
  USE DIFFERENT blocks for walls, floor, and ceiling! Mix textures creatively.
- **roof_type** (str): How the roof looks. Use "peaked" for houses, "dome" for temples, etc.
- **num_floors** (int, 1-4): Multi-story buildings. Each floor gets its own interior.
- **has_windows** (bool): Whether to add windows to the walls.
- **has_door** (bool): Whether to add a door at ground level.
- **exterior_type** (str): "garden", "fence", "porch", "wall", or "none".
- **details** (list[BlockPlacement]): **15-40 decorative blocks per room**.
  Coordinates: 1 <= x < width-1, 1 <= y < height-1, 1 <= z < depth-1.
- **mobs** (list[MobSpawn]): Entities inside. Villagers for towns, monsters for dungeons.
- **loot_chests** (list[LootChest]): 0-2 chests per room.

### Corridor / Path
- **width** (int, 2-7), **height** (int, 3-5), **length** (int, 3-20)
- **block** (str): Block ID for the path/corridor material.
- **is_path** (bool): true for open-air paths (villages), false for enclosed corridors (dungeons).

## ARCHITECTURAL DESIGN GUIDELINES

### For VILLAGES / SETTLEMENTS
- Create 3-5 buildings of DIFFERENT sizes and purposes (house, shop, tavern, church, well).
- Use wood planks (oak, spruce, dark_oak) for walls and wood logs for framing.
- Use "peaked" or "gable" roofs. Set has_windows=true and has_door=true.
- Set exterior_type to "fence" or "garden". Use layout="grid" or layout="cluster".
- Place villagers, cats, and iron_golems as mobs. No hostile mobs.
- Details: crafting tables, furnaces, flower pots, bookshelves, beds (use wool).
- Corridors should be paths (is_path=true) using gravel, cobblestone, or dirt.

### For CASTLES / FORTRESSES
- Create 2-4 connected sections (gatehouse, courtyard, throne room, tower).
- Use stone_bricks, deepslate_bricks, or polished_blackstone for walls.
- Mix in cracked/mossy variants for age. Use iron_bars for windows.
- Set roof_type="flat" with battlements. exterior_type="wall".
- Details: banners (wool), weapon racks (anvils), throne (stairs + wool).
- Corridors are enclosed stone passages.

### For TOWERS
- 1-2 rooms with num_floors=2-4 and tall height (12-20).
- Spiral staircase simulation with detail blocks.
- Use "peaked" or "dome" roof. has_windows=true.
- Top floor gets a beacon or lookout platform.

### For TEMPLES / CATHEDRALS
- Tall central hall (height 10-15) with columns and stained glass.
- Use "dome" roof. layout="circular" for temple complexes.
- Details: candles, enchanting tables, lecterns, end_rods, gold_blocks.
- Place pillars using shell_block from floor to ceiling.

### For HOUSES / COTTAGES
- Small (7x5x7 to 12x6x12) cozy buildings.
- Wood walls, stone floor, "peaked" roof. has_windows=true, has_door=true.
- exterior_type="garden" or "fence". num_floors=1 or 2.
- Details: crafting table, furnace, bed (wool blocks), flower pots.

### For SHIPS
- Long narrow shape (width 8-12, depth 15-25).
- Use oak/spruce/dark_oak planks. "none" roof (open deck).
- Details: fences as railings, wool as sails, chains and lanterns.
- Slightly elevated (build at y+3 for hull depth).

### Key rules for ALL structure types:
1. **ALWAYS place 15+ details per room.** Empty rooms are BORING.
2. **Build vertically** — use the full height with pillars, hanging features.
3. **Create focal points** — every room needs something interesting to look at.
4. **Use contrasting materials** — don't use the same block for everything.
5. **Match the theme** — village houses get wood, castles get stone, nether gets blackstone.
6. **Set building features** — use roof_type, has_windows, has_door, exterior_type!

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
    structure_type: str,
    narrative_context: dict[str, Any] | None,
) -> str:
    """Assemble the user message sent to the model."""
    parts: list[str] = []

    parts.append(
        f"Design a UNIQUE Minecraft **{structure_type}** with the **{palette}** theme."
    )
    parts.append(f'Player request: "{prompt}"')
    parts.append(
        f"IMPORTANT DESIGN REQUIREMENTS:\n"
        f"- Set structure_type to \"{structure_type}\".\n"
        f"- Create 2-4 rooms/buildings with VARIED sizes.\n"
        f"- Each room MUST have 15-40 detail blocks.\n"
        f"- Set roof_type, has_windows, has_door, and exterior_type appropriately.\n"
        f"- For villages/settlements: use layout=\"grid\" or \"cluster\", is_path=true.\n"
        f"- For single buildings: use layout=\"single\".\n"
        f"- Build PILLARS using columns of blocks (4+ blocks stacked vertically).\n"
        f"- Add LIGHTING (lanterns, torches, campfires) for atmosphere.\n"
        f"- Place DECORATIVE blocks (iron_bars, cobwebs, skulls, bookshelves).\n"
        f"- Use the full height of each room — don't leave upper space empty.\n"
        f"- Make each room architecturally distinct with a clear theme."
    )

    if narrative_context:
        ctx_lines: list[str] = []
        for key, value in narrative_context.items():
            ctx_lines.append(f"- {key}: {value}")
        parts.append("Narrative context:\n" + "\n".join(ctx_lines))

    parts.append(
        "Return the structure blueprint as a JSON object that follows the schema "
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
    """Clean up a raw blueprint dict in-place, replacing invalid IDs with safe defaults."""
    # Ensure structure_type is valid
    if data.get("structure_type") and data["structure_type"] not in VALID_STRUCTURE_TYPES:
        data["structure_type"] = "dungeon"

    # Ensure layout is valid
    if data.get("layout") and data["layout"] not in VALID_LAYOUT_TYPES:
        data["layout"] = "linear"

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
                if not cleaned:
                    cleaned = ["minecraft:iron_sword"]
                chest["items"] = cleaned

        # Clamp room dimensions
        if "width" in room:
            room["width"] = max(5, min(30, room["width"]))
        if "height" in room:
            room["height"] = max(4, min(20, room["height"]))
        if "depth" in room:
            room["depth"] = max(5, min(30, room["depth"]))

        # Fix roof_type
        if room.get("roof_type") and room["roof_type"] not in VALID_ROOF_TYPES:
            room["roof_type"] = "none"

        # Clamp num_floors
        if "num_floors" in room:
            room["num_floors"] = max(1, min(4, room["num_floors"]))

        # Fix exterior_type
        valid_exteriors = {"garden", "fence", "porch", "wall", "none"}
        if room.get("exterior_type") and room["exterior_type"] not in valid_exteriors:
            room["exterior_type"] = "none"

    # Fix corridor blocks
    for corridor in data.get("corridors", []):
        if corridor.get("block") and corridor["block"] not in VALID_BLOCK_IDS:
            logger.warning("Replacing invalid corridor block '%s' with '%s'", corridor["block"], _DEFAULT_BLOCK)
            corridor["block"] = _DEFAULT_BLOCK
        if "width" in corridor:
            corridor["width"] = max(2, min(7, corridor["width"]))
        if "height" in corridor:
            corridor["height"] = max(3, min(5, corridor["height"]))
        if "length" in corridor:
            corridor["length"] = max(3, min(20, corridor["length"]))


# ---------------------------------------------------------------------------
# JSON repair for truncated AI responses
# ---------------------------------------------------------------------------


def _repair_json(raw: str) -> dict:
    """Attempt to repair truncated JSON from the AI."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    for trim in range(0, min(1500, len(text))):
        attempt = text[:len(text) - trim] if trim > 0 else text
        attempt = attempt.rstrip()

        while attempt and attempt[-1] in (',', ':'):
            attempt = attempt[:-1].rstrip()

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

            if "rooms" in data and "corridors" in data:
                n_rooms = len(data["rooms"])
                needed = max(0, n_rooms - 1)
                data["corridors"] = data["corridors"][:needed]
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
    """Call NVIDIA NIM to generate a structure blueprint.

    Parameters
    ----------
    prompt:
        Free-form player request describing the desired structure.
    palette:
        Visual theme keyword (e.g. "stone", "nether", "deepslate", "wood").
    narrative_context:
        Optional dictionary of extra context.

    Returns
    -------
    Blueprint
        A fully-validated structure blueprint.
    """
    # Detect structure type from prompt
    structure_type = _detect_structure_type(prompt)

    user_message = _build_user_prompt(prompt, palette, structure_type, narrative_context)

    logger.info(
        "Sending blueprint generation request to NIM (%s) — structure_type=%s",
        settings.nim_model, structure_type,
    )
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

    try:
        raw_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed (%s), attempting repair...", e)
        raw_data = _repair_json(raw_content)

    _sanitize_blueprint(raw_data)

    blueprint = Blueprint.model_validate(raw_data)
    blueprint.palette = palette
    # Ensure structure_type is set correctly
    if blueprint.structure_type == "dungeon" and structure_type != "dungeon":
        blueprint.structure_type = structure_type

    logger.info(
        "Blueprint '%s' generated: type=%s, %d room(s), %d corridor(s)",
        blueprint.name,
        blueprint.structure_type,
        len(blueprint.rooms),
        len(blueprint.corridors),
    )
    return blueprint


# ---------------------------------------------------------------------------
# Fallback blueprints
# ---------------------------------------------------------------------------

def get_fallback_blueprint(palette: str = "stone", structure_type: str = "dungeon") -> Blueprint:
    """Return a safe, hardcoded structure as fallback.

    Picks a different fallback based on the detected structure type.
    """
    if structure_type in ("village", "marketplace", "farm"):
        return _fallback_village(palette)
    elif structure_type in ("house", "cottage", "tavern"):
        return _fallback_house(palette)
    elif structure_type in ("castle", "fort", "fortress"):
        return _fallback_castle(palette)
    elif structure_type in ("tower", "lighthouse"):
        return _fallback_tower(palette)
    else:
        return _fallback_dungeon(palette)


def _fallback_dungeon(palette: str) -> Blueprint:
    """Classic dungeon fallback."""
    return Blueprint(
        name="Emergency Vault",
        palette=palette,
        structure_type="dungeon",
        layout="linear",
        rooms=[
            Room(
                name="Vault Chamber",
                width=10, height=6, depth=10,
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
                    LootChest(x=5, y=1, z=1, items=[
                        "minecraft:iron_sword", "minecraft:bread",
                        "minecraft:iron_ingot", "minecraft:golden_apple",
                    ]),
                ],
            ),
        ],
        corridors=[],
    )


def _fallback_village(palette: str) -> Blueprint:
    """Small village fallback with two buildings."""
    return Blueprint(
        name="Traveler's Rest",
        palette=palette,
        structure_type="village",
        layout="grid",
        rooms=[
            Room(
                name="Farmer's Cottage",
                width=8, height=5, depth=8,
                shell_block="minecraft:oak_planks",
                floor_block="minecraft:cobblestone",
                ceiling_block="minecraft:oak_planks",
                roof_type="peaked",
                has_windows=True,
                has_door=True,
                exterior_type="fence",
                details=[
                    BlockPlacement(block="minecraft:furnace", x=1, y=1, z=1),
                    BlockPlacement(block="minecraft:crafting_table", x=2, y=1, z=1),
                    BlockPlacement(block="minecraft:lantern", x=4, y=4, z=4),
                    BlockPlacement(block="minecraft:bookshelf", x=6, y=1, z=1),
                    BlockPlacement(block="minecraft:bookshelf", x=6, y=2, z=1),
                    BlockPlacement(block="minecraft:flower_pot", x=3, y=1, z=6),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:villager", x=3, y=1, z=3, count=1),
                    MobSpawn(entity="minecraft:cat", x=5, y=1, z=5, count=1),
                ],
                loot_chests=[
                    LootChest(x=1, y=1, z=6, items=[
                        "minecraft:bread", "minecraft:iron_ingot",
                        "minecraft:coal", "minecraft:bread",
                    ]),
                ],
            ),
            Room(
                name="Village Well House",
                width=6, height=5, depth=6,
                shell_block="minecraft:cobblestone",
                floor_block="minecraft:stone_bricks",
                ceiling_block="minecraft:oak_planks",
                roof_type="peaked",
                has_windows=True,
                has_door=True,
                exterior_type="none",
                details=[
                    BlockPlacement(block="minecraft:cauldron", x=3, y=1, z=3),
                    BlockPlacement(block="minecraft:lantern", x=3, y=4, z=3),
                    BlockPlacement(block="minecraft:chain", x=3, y=3, z=3),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:villager", x=2, y=1, z=2, count=1),
                ],
                loot_chests=[],
            ),
        ],
        corridors=[
            Corridor(width=3, height=3, length=5, block="minecraft:gravel", is_path=True),
        ],
    )


def _fallback_house(palette: str) -> Blueprint:
    """Single house fallback."""
    return Blueprint(
        name="Woodland Cottage",
        palette=palette,
        structure_type="house",
        layout="single",
        rooms=[
            Room(
                name="Cozy Cottage",
                width=10, height=6, depth=10,
                shell_block="minecraft:spruce_planks",
                floor_block="minecraft:cobblestone",
                ceiling_block="minecraft:spruce_planks",
                roof_type="peaked",
                num_floors=1,
                has_windows=True,
                has_door=True,
                exterior_type="garden",
                details=[
                    BlockPlacement(block="minecraft:furnace", x=1, y=1, z=1),
                    BlockPlacement(block="minecraft:crafting_table", x=2, y=1, z=1),
                    BlockPlacement(block="minecraft:red_wool", x=7, y=1, z=7),
                    BlockPlacement(block="minecraft:red_wool", x=8, y=1, z=7),
                    BlockPlacement(block="minecraft:white_wool", x=7, y=1, z=8),
                    BlockPlacement(block="minecraft:white_wool", x=8, y=1, z=8),
                    BlockPlacement(block="minecraft:lantern", x=5, y=5, z=5),
                    BlockPlacement(block="minecraft:bookshelf", x=1, y=1, z=8),
                    BlockPlacement(block="minecraft:bookshelf", x=1, y=2, z=8),
                    BlockPlacement(block="minecraft:flower_pot", x=5, y=1, z=1),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:cat", x=5, y=1, z=5, count=1),
                ],
                loot_chests=[
                    LootChest(x=8, y=1, z=1, items=[
                        "minecraft:bread", "minecraft:iron_sword",
                        "minecraft:torch", "minecraft:compass",
                    ]),
                ],
            ),
        ],
        corridors=[],
    )


def _fallback_castle(palette: str) -> Blueprint:
    """Castle fallback with gatehouse and throne room."""
    return Blueprint(
        name="Stoneguard Keep",
        palette=palette,
        structure_type="castle",
        layout="linear",
        rooms=[
            Room(
                name="Gatehouse",
                width=10, height=8, depth=8,
                shell_block="minecraft:stone_bricks",
                floor_block="minecraft:stone_bricks",
                ceiling_block="minecraft:stone_bricks",
                roof_type="flat",
                has_windows=False,
                has_door=True,
                exterior_type="wall",
                details=[
                    BlockPlacement(block="minecraft:iron_bars", x=1, y=3, z=1),
                    BlockPlacement(block="minecraft:iron_bars", x=8, y=3, z=1),
                    BlockPlacement(block="minecraft:lantern", x=5, y=7, z=4),
                    BlockPlacement(block="minecraft:chain", x=5, y=6, z=4),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:iron_golem", x=5, y=1, z=4, count=1),
                ],
                loot_chests=[],
            ),
            Room(
                name="Throne Hall",
                width=15, height=10, depth=20,
                shell_block="minecraft:stone_bricks",
                floor_block="minecraft:polished_deepslate",
                ceiling_block="minecraft:stone_bricks",
                roof_type="flat",
                has_windows=True,
                has_door=False,
                details=[
                    BlockPlacement(block="minecraft:gold_block", x=7, y=1, z=17),
                    BlockPlacement(block="minecraft:gold_block", x=7, y=2, z=17),
                    BlockPlacement(block="minecraft:red_wool", x=7, y=3, z=17),
                    BlockPlacement(block="minecraft:red_wool", x=7, y=1, z=5),
                    BlockPlacement(block="minecraft:red_wool", x=7, y=1, z=8),
                    BlockPlacement(block="minecraft:red_wool", x=7, y=1, z=11),
                    BlockPlacement(block="minecraft:red_wool", x=7, y=1, z=14),
                    BlockPlacement(block="minecraft:lantern", x=3, y=9, z=5),
                    BlockPlacement(block="minecraft:lantern", x=11, y=9, z=5),
                    BlockPlacement(block="minecraft:lantern", x=3, y=9, z=15),
                    BlockPlacement(block="minecraft:lantern", x=11, y=9, z=15),
                    BlockPlacement(block="minecraft:chain", x=3, y=8, z=5),
                    BlockPlacement(block="minecraft:chain", x=11, y=8, z=5),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:villager", x=7, y=1, z=16, count=1),
                    MobSpawn(entity="minecraft:iron_golem", x=3, y=1, z=10, count=1),
                ],
                loot_chests=[
                    LootChest(x=13, y=1, z=18, items=[
                        "minecraft:diamond_sword", "minecraft:golden_apple",
                        "minecraft:diamond", "minecraft:emerald",
                    ]),
                ],
            ),
        ],
        corridors=[
            Corridor(width=5, height=5, length=8, block="minecraft:stone_bricks"),
        ],
    )


def _fallback_tower(palette: str) -> Blueprint:
    """Tower fallback."""
    return Blueprint(
        name="Sentinel Spire",
        palette=palette,
        structure_type="tower",
        layout="single",
        rooms=[
            Room(
                name="Watchtower",
                width=8, height=16, depth=8,
                shell_block="minecraft:stone_bricks",
                floor_block="minecraft:cobblestone",
                ceiling_block="minecraft:stone_bricks",
                roof_type="peaked",
                num_floors=3,
                has_windows=True,
                has_door=True,
                details=[
                    BlockPlacement(block="minecraft:lantern", x=4, y=4, z=4),
                    BlockPlacement(block="minecraft:lantern", x=4, y=9, z=4),
                    BlockPlacement(block="minecraft:lantern", x=4, y=14, z=4),
                    BlockPlacement(block="minecraft:chain", x=4, y=13, z=4),
                    BlockPlacement(block="minecraft:bookshelf", x=1, y=6, z=1),
                    BlockPlacement(block="minecraft:bookshelf", x=1, y=7, z=1),
                    BlockPlacement(block="minecraft:lectern", x=2, y=6, z=1),
                ],
                mobs=[
                    MobSpawn(entity="minecraft:villager", x=4, y=1, z=4, count=1),
                ],
                loot_chests=[
                    LootChest(x=6, y=1, z=6, items=[
                        "minecraft:spyglass", "minecraft:bow",
                        "minecraft:arrow", "minecraft:bread",
                    ]),
                ],
            ),
        ],
        corridors=[],
    )


# ---------------------------------------------------------------------------
# Quest generation via Nemotron
# ---------------------------------------------------------------------------

_QUEST_SYSTEM_PROMPT = f"""\
You are NemoCraft Quest Master, an expert at creating immersive Minecraft quests
that guide players through a living world. You generate quests as JSON arrays.

Each quest MUST lead to a specific location type (dungeon, village, temple, castle,
mine, fort, arena, library, etc.) and include objectives that make sense for that
destination.

## Quest JSON Schema

Return a JSON object with a single key "quests" containing an array of quest objects.
Each quest object has these fields:

- **name** (str): A creative, evocative quest name (e.g. "The Warden's Last Stand").
- **description** (str): 1-3 sentence story hook explaining why the player should care.
- **giver** (str): Name and title of the NPC offering the quest (e.g. "Captain Ironhelm").
- **destination_type** (str): One of: dungeon, village, temple, castle, tower, house,
  marketplace, fort, arena, library, mine, monument, ruins, ship, prison, tavern, farm.
- **destination_prompt** (str): A detailed prompt describing the structure to generate
  at the quest destination (this gets fed to the structure generator AI). Be vivid and
  specific about blocks, atmosphere, and layout.
- **objectives** (array): 1-3 objectives, each with:
  - **description** (str): Human-readable objective text shown to the player.
  - **objective_type** (str): One of: kill, explore, collect, escort, build, survive, clear_dungeon.
  - **target** (str): The Minecraft entity/item/location ID. For kill objectives use
    entity IDs like "minecraft:zombie". For collect objectives use item IDs. For
    explore/build/survive objectives use a descriptive location tag.
  - **target_count** (int): How many to kill/collect/place (1-20).
- **rewards** (object):
  - **items** (array of str): 2-4 Minecraft item IDs from the valid list below.
  - **experience** (int): XP points to award (100-1000).

## Valid entity IDs for kill objectives
{json.dumps(sorted(list(VALID_ENTITY_IDS)), indent=0)}

## Valid item IDs for rewards and collect objectives
{json.dumps(sorted(list(VALID_ITEM_IDS)), indent=0)}

## Rules
1. Make quests feel like part of an ongoing story — reference the player's actions.
2. Vary objective types within a quest (don't make all objectives the same type).
3. Match quest difficulty to the narrative difficulty level provided.
4. Make destination_prompt DETAILED — it will be used to generate the actual structure.
5. Quest givers should have distinct personalities and titles.
6. Never repeat quest names from the recent_completed list.
7. Output **only** the JSON object — no markdown fences, no commentary.
"""


async def generate_quests(
    player_name: str,
    playstyle: str,
    intensity: float,
    narrative_context: dict,
    num_quests: int = 2,
    recent_completed: list[str] | None = None,
) -> list:
    """Call Nemotron to generate quests based on player context.

    Returns a list of Quest-compatible dicts that can be validated with
    the Quest pydantic model.
    """
    from backend.quests import Quest, QuestObjective, QuestReward

    recent = recent_completed or []
    user_parts = [
        f"Generate {num_quests} unique quests for player \"{player_name}\".",
        f"Player playstyle: {playstyle} (intensity: {intensity:.2f}).",
        f"Narrative context: theme={narrative_context.get('theme', 'mystery')}, "
        f"mood={narrative_context.get('mood', 'ancient')}, "
        f"difficulty={narrative_context.get('difficulty_level', 5)}, "
        f"story_hook=\"{narrative_context.get('story_hook', '')}\".",
    ]
    if recent:
        user_parts.append(
            f"Do NOT reuse these recent quest names: {json.dumps(recent)}"
        )
    user_parts.append(
        "Return a JSON object with a 'quests' array. "
        "Each quest should lead to a different type of destination. "
        "Make the quests feel connected to the narrative theme."
    )

    user_message = "\n".join(user_parts)

    logger.info("Generating %d quests via Nemotron for player %s", num_quests, player_name)

    response = await _client.chat.completions.create(
        model=settings.nim_model,
        messages=[
            {"role": "system", "content": _QUEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.9,
        top_p=0.95,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content
    logger.debug("Raw quest response: %s", raw_content)

    try:
        raw_data = json.loads(raw_content)
    except json.JSONDecodeError:
        raw_data = _repair_json(raw_content)

    quest_list = raw_data.get("quests", [])
    if not isinstance(quest_list, list):
        quest_list = [raw_data] if "name" in raw_data else []

    quests = []
    for q_data in quest_list[:num_quests]:
        try:
            # Sanitize reward items
            rewards_data = q_data.get("rewards", {})
            if "items" in rewards_data:
                rewards_data["items"] = [
                    item for item in rewards_data["items"]
                    if item in VALID_ITEM_IDS
                ] or ["minecraft:iron_sword"]

            # Sanitize objective targets for kill types
            for obj in q_data.get("objectives", []):
                if obj.get("objective_type") == "kill":
                    if obj.get("target") not in VALID_ENTITY_IDS:
                        obj["target"] = "minecraft:zombie"
                if obj.get("target_count", 1) < 1:
                    obj["target_count"] = 1
                if obj.get("target_count", 1) > 20:
                    obj["target_count"] = 20

            quest = Quest(
                name=q_data.get("name", "Unnamed Quest"),
                description=q_data.get("description", "A mysterious quest awaits."),
                giver=q_data.get("giver", "A mysterious traveler"),
                objectives=[
                    QuestObjective(**obj) for obj in q_data.get("objectives", [
                        {"description": "Explore the unknown", "objective_type": "explore",
                         "target": "unknown_location", "target_count": 1}
                    ])
                ],
                rewards=QuestReward(**rewards_data),
                destination_type=q_data.get("destination_type", "dungeon"),
                destination_prompt=q_data.get("destination_prompt", "A mysterious dungeon"),
                difficulty=narrative_context.get("difficulty_level", 5),
            )
            quests.append(quest)
        except Exception as e:
            logger.warning("Failed to parse quest from AI response: %s", e)
            continue

    logger.info("Generated %d quests via Nemotron", len(quests))
    return quests
