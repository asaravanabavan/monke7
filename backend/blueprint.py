"""
Pydantic v2 models that describe a NemoCraft structure blueprint.

A Blueprint contains one or more Rooms connected by Corridors (or paths for
villages).  Each Room can hold block detail placements, mob spawns, and loot
chests.  All identifiers are validated against the registries in registries.py.

Supports multiple structure types: dungeons, villages, castles, towers,
temples, houses, marketplaces, ships, treehouses, forts, and more.
"""

from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Literal

from backend.registries import VALID_BLOCK_IDS, VALID_ENTITY_IDS, VALID_ITEM_IDS


# ---------------------------------------------------------------------------
# Valid structure types and building features
# ---------------------------------------------------------------------------

VALID_STRUCTURE_TYPES = {
    "dungeon", "village", "castle", "tower", "house", "temple",
    "marketplace", "fort", "treehouse", "ship", "ruins", "cathedral",
    "mansion", "tavern", "farm", "lighthouse", "bridge", "arena",
    "library", "prison", "mine", "outpost", "monument",
}

VALID_ROOF_TYPES = {"flat", "peaked", "gable", "dome", "none"}

VALID_LAYOUT_TYPES = {"linear", "grid", "circular", "cluster", "single"}


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------

class BlockPlacement(BaseModel):
    """A single block placed at an (x, y, z) position inside a room."""

    block: str
    x: int
    y: int
    z: int

    @field_validator("block")
    @classmethod
    def block_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BLOCK_IDS:
            raise ValueError(
                f"Invalid block ID '{v}'. Must be one of the registered "
                f"Minecraft 1.20.1 block IDs (e.g. 'minecraft:stone_bricks')."
            )
        return v


class MobSpawn(BaseModel):
    """A mob spawn point inside a room."""

    entity: str
    x: int
    y: int
    z: int
    count: int = 1

    @field_validator("entity")
    @classmethod
    def entity_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ENTITY_IDS:
            raise ValueError(
                f"Invalid entity ID '{v}'. Must be one of the registered "
                f"Minecraft 1.20.1 entity IDs (e.g. 'minecraft:zombie')."
            )
        return v

    @field_validator("count")
    @classmethod
    def count_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"Mob count must be at least 1, got {v}.")
        return v


class LootChest(BaseModel):
    """A chest placed at (x, y, z) containing the listed items."""

    x: int
    y: int
    z: int
    items: list[str]

    @field_validator("items")
    @classmethod
    def items_must_be_valid(cls, v: list[str]) -> list[str]:
        for item in v:
            if item not in VALID_ITEM_IDS:
                raise ValueError(
                    f"Invalid item ID '{item}'. Must be one of the registered "
                    f"Minecraft 1.20.1 item IDs (e.g. 'minecraft:diamond_sword')."
                )
        return v


# ---------------------------------------------------------------------------
# Room & Corridor
# ---------------------------------------------------------------------------

class Room(BaseModel):
    """A building/room in the structure.

    For villages, each Room represents a separate building.
    For dungeons, each Room is a chamber in the dungeon.
    """

    name: str
    width: int    # X dimension, 5-30
    height: int   # Y dimension, 4-20
    depth: int    # Z dimension, 5-30
    shell_block: str = "minecraft:stone_bricks"
    floor_block: str = "minecraft:stone_bricks"
    ceiling_block: str = "minecraft:stone_bricks"
    details: list[BlockPlacement] = []
    mobs: list[MobSpawn] = []
    loot_chests: list[LootChest] = []

    # Building features
    roof_type: str = "none"        # flat, peaked, gable, dome, none
    num_floors: int = 1            # multi-story support (1-4)
    has_windows: bool = False
    has_door: bool = False
    exterior_type: str = "none"    # garden, fence, porch, wall, none

    @field_validator("width")
    @classmethod
    def width_in_range(cls, v: int) -> int:
        if not 5 <= v <= 30:
            v = max(5, min(30, v))
        return v

    @field_validator("height")
    @classmethod
    def height_in_range(cls, v: int) -> int:
        if not 4 <= v <= 20:
            v = max(4, min(20, v))
        return v

    @field_validator("depth")
    @classmethod
    def depth_in_range(cls, v: int) -> int:
        if not 5 <= v <= 30:
            v = max(5, min(30, v))
        return v

    @field_validator("shell_block", "floor_block", "ceiling_block")
    @classmethod
    def room_blocks_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BLOCK_IDS:
            raise ValueError(
                f"Invalid block ID '{v}'. Must be one of the registered "
                f"Minecraft 1.20.1 block IDs."
            )
        return v

    @field_validator("roof_type")
    @classmethod
    def roof_type_valid(cls, v: str) -> str:
        if v not in VALID_ROOF_TYPES:
            return "none"
        return v

    @field_validator("num_floors")
    @classmethod
    def num_floors_in_range(cls, v: int) -> int:
        return max(1, min(4, v))

    @field_validator("exterior_type")
    @classmethod
    def exterior_type_valid(cls, v: str) -> str:
        valid = {"garden", "fence", "porch", "wall", "none"}
        if v not in valid:
            return "none"
        return v


class Corridor(BaseModel):
    """A corridor/path that connects two adjacent rooms/buildings.

    For dungeons: enclosed corridors.
    For villages: open paths/roads between buildings.
    """

    width: int = 3    # 2-7
    height: int = 3   # 3-5
    length: int = 5   # 3-20
    block: str = "minecraft:stone_bricks"
    is_path: bool = False  # True for open-air village paths

    @field_validator("width")
    @classmethod
    def width_in_range(cls, v: int) -> int:
        if not 2 <= v <= 7:
            v = max(2, min(7, v))
        return v

    @field_validator("height")
    @classmethod
    def height_in_range(cls, v: int) -> int:
        if not 3 <= v <= 5:
            v = max(3, min(5, v))
        return v

    @field_validator("length")
    @classmethod
    def length_in_range(cls, v: int) -> int:
        if not 3 <= v <= 20:
            v = max(3, min(20, v))
        return v

    @field_validator("block")
    @classmethod
    def block_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BLOCK_IDS:
            return "minecraft:stone_bricks"
        return v


# ---------------------------------------------------------------------------
# Top-level Blueprint
# ---------------------------------------------------------------------------

class Blueprint(BaseModel):
    """
    Complete structure blueprint.

    A blueprint must contain at least one room.  When there are N rooms
    (N > 1) there must be exactly N-1 corridors/paths connecting them.
    """

    name: str
    palette: str = "stone"
    structure_type: str = "dungeon"
    layout: str = "linear"
    rooms: list[Room]
    corridors: list[Corridor] = []

    @field_validator("structure_type")
    @classmethod
    def structure_type_valid(cls, v: str) -> str:
        if v not in VALID_STRUCTURE_TYPES:
            return "dungeon"
        return v

    @field_validator("layout")
    @classmethod
    def layout_valid(cls, v: str) -> str:
        if v not in VALID_LAYOUT_TYPES:
            return "linear"
        return v

    @field_validator("rooms")
    @classmethod
    def must_have_at_least_one_room(cls, v: list[Room]) -> list[Room]:
        if len(v) < 1:
            raise ValueError("A blueprint must contain at least one room.")
        return v

    @model_validator(mode="after")
    def corridors_match_rooms(self) -> "Blueprint":
        n_rooms = len(self.rooms)
        n_corridors = len(self.corridors)
        if n_rooms > 1 and n_corridors != n_rooms - 1:
            raise ValueError(
                f"When there are {n_rooms} rooms there must be exactly "
                f"{n_rooms - 1} corridor(s) connecting them, but got "
                f"{n_corridors}."
            )
        return self
