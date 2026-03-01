"""
Pydantic v2 models that describe a NemoCraft dungeon blueprint.

A Blueprint contains one or more Rooms connected by Corridors.
Each Room can hold block detail placements, mob spawns, and loot chests.
All identifiers are validated against the registries in registries.py.
"""

from pydantic import BaseModel, field_validator, model_validator
from typing import Optional

from backend.registries import VALID_BLOCK_IDS, VALID_ENTITY_IDS, VALID_ITEM_IDS


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
    """A rectangular room in the dungeon."""

    name: str
    width: int    # X dimension, 5-25
    height: int   # Y dimension, 4-15
    depth: int    # Z dimension, 5-25
    shell_block: str = "minecraft:stone_bricks"
    floor_block: str = "minecraft:stone_bricks"
    ceiling_block: str = "minecraft:stone_bricks"
    details: list[BlockPlacement] = []
    mobs: list[MobSpawn] = []
    loot_chests: list[LootChest] = []

    @field_validator("width")
    @classmethod
    def width_in_range(cls, v: int) -> int:
        if not 5 <= v <= 25:
            raise ValueError(f"Room width must be between 5 and 25, got {v}.")
        return v

    @field_validator("height")
    @classmethod
    def height_in_range(cls, v: int) -> int:
        if not 4 <= v <= 15:
            raise ValueError(f"Room height must be between 4 and 15, got {v}.")
        return v

    @field_validator("depth")
    @classmethod
    def depth_in_range(cls, v: int) -> int:
        if not 5 <= v <= 25:
            raise ValueError(f"Room depth must be between 5 and 25, got {v}.")
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


class Corridor(BaseModel):
    """A corridor that connects two adjacent rooms."""

    width: int = 3    # 2-5
    height: int = 3   # 3-5
    length: int = 5   # 3-15
    block: str = "minecraft:stone_bricks"

    @field_validator("width")
    @classmethod
    def width_in_range(cls, v: int) -> int:
        if not 2 <= v <= 5:
            raise ValueError(f"Corridor width must be between 2 and 5, got {v}.")
        return v

    @field_validator("height")
    @classmethod
    def height_in_range(cls, v: int) -> int:
        if not 3 <= v <= 5:
            raise ValueError(f"Corridor height must be between 3 and 5, got {v}.")
        return v

    @field_validator("length")
    @classmethod
    def length_in_range(cls, v: int) -> int:
        if not 3 <= v <= 15:
            raise ValueError(f"Corridor length must be between 3 and 15, got {v}.")
        return v

    @field_validator("block")
    @classmethod
    def block_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BLOCK_IDS:
            raise ValueError(
                f"Invalid block ID '{v}'. Must be one of the registered "
                f"Minecraft 1.20.1 block IDs."
            )
        return v


# ---------------------------------------------------------------------------
# Top-level Blueprint
# ---------------------------------------------------------------------------

class Blueprint(BaseModel):
    """
    Complete dungeon blueprint.

    A blueprint must contain at least one room.  When there are N rooms
    (N > 1) there must be exactly N-1 corridors connecting them.
    """

    name: str
    palette: str = "stone"
    rooms: list[Room]
    corridors: list[Corridor] = []

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
