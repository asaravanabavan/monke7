"""Room placement solver — lays out rooms in a linear chain along +Z."""

from pydantic import BaseModel
from backend.blueprint import Blueprint, Room, Corridor

class PlacedRoom(BaseModel):
    """A room with absolute world coordinates."""
    name: str
    # Origin is the minimum corner (most negative x, y, z)
    origin_x: int
    origin_y: int
    origin_z: int
    width: int   # X
    height: int  # Y
    depth: int   # Z
    shell_block: str
    floor_block: str
    ceiling_block: str
    details: list  # BlockPlacement dicts with absolute coords
    mobs: list     # MobSpawn dicts with absolute coords
    loot_chests: list  # LootChest dicts with absolute coords

class PlacedCorridor(BaseModel):
    """A corridor connecting two rooms with absolute world coordinates."""
    origin_x: int
    origin_y: int
    origin_z: int
    width: int
    height: int
    length: int  # Z extent
    block: str

class PlacedBlueprint(BaseModel):
    """Blueprint with all coordinates resolved to absolute world positions."""
    name: str
    rooms: list[PlacedRoom]
    corridors: list[PlacedCorridor]
    karma_tier: str = "neutral"

def solve_placement(blueprint: Blueprint, player_x: int, player_y: int, player_z: int, karma_tier: str = "neutral") -> PlacedBlueprint:
    """
    Place rooms in a linear chain along +Z starting from the player's position.

    Layout: Room₀ → Corridor₀ → Room₁ → Corridor₁ → Room₂ → ...
    Rooms are X-centered on player_x, placed at player_y for floor level.
    """
    placed_rooms = []
    placed_corridors = []
    import random

    # Start building 5 blocks in front of the player (+Z)
    current_z = player_z + 5
    current_x = player_x
    current_y = player_y  # Floor level

    for i, room in enumerate(blueprint.rooms):
        # Vary the X and Y occasionally so it's not a straight flat line
        if i > 0:
            x_shift = random.randint(-4, 4)
            current_x += x_shift
            
            y_shift = random.choice([-2, -1, 0, 1, 2])
            current_y += y_shift

        # X-center the room on current_x
        origin_x = current_x - room.width // 2
        origin_y = current_y
        origin_z = current_z

        # Convert relative detail/mob/chest coordinates to absolute
        abs_details = []
        for d in room.details:
            abs_details.append({
                "block": d.block,
                "x": origin_x + d.x,
                "y": origin_y + d.y,
                "z": origin_z + d.z,
            })

        abs_mobs = []
        for m in room.mobs:
            abs_mobs.append({
                "entity": m.entity,
                "x": origin_x + m.x,
                "y": origin_y + m.y,
                "z": origin_z + m.z,
                "count": m.count,
            })

        abs_chests = []
        for c in room.loot_chests:
            abs_chests.append({
                "x": origin_x + c.x,
                "y": origin_y + c.y,
                "z": origin_z + c.z,
                "items": c.items,
            })

        placed_rooms.append(PlacedRoom(
            name=room.name,
            origin_x=origin_x,
            origin_y=origin_y,
            origin_z=origin_z,
            width=room.width,
            height=room.height,
            depth=room.depth,
            shell_block=room.shell_block,
            floor_block=room.floor_block,
            ceiling_block=room.ceiling_block,
            details=abs_details,
            mobs=abs_mobs,
            loot_chests=abs_chests,
        ))

        # Advance Z past this room
        current_z += room.depth

        # Place corridor if not the last room
        if i < len(blueprint.corridors):
            corridor = blueprint.corridors[i]
            cor_origin_x = current_x - corridor.width // 2
            cor_origin_y = current_y
            cor_origin_z = current_z

            placed_corridors.append(PlacedCorridor(
                origin_x=cor_origin_x,
                origin_y=cor_origin_y,
                origin_z=cor_origin_z,
                width=corridor.width,
                height=corridor.height,
                length=corridor.length,
                block=corridor.block,
            ))

            # Advance Z past corridor
            current_z += corridor.length

    return PlacedBlueprint(
        name=blueprint.name,
        rooms=placed_rooms,
        corridors=placed_corridors,
        karma_tier=karma_tier,
    )
