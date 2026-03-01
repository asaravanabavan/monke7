"""Room placement solver — supports multiple layout strategies.

Layout types:
- **linear**: Rooms chained along +Z with corridors (classic dungeon).
- **grid**: Buildings arranged in a grid pattern with paths (village style).
- **circular**: Buildings arranged in a ring around a central point.
- **cluster**: Buildings placed in organic clusters with paths.
- **single**: Single building with no corridors.
"""

import math
import random
from pydantic import BaseModel
from backend.blueprint import Blueprint, Room, Corridor


class PlacedRoom(BaseModel):
    """A room/building with absolute world coordinates."""
    name: str
    origin_x: int
    origin_y: int
    origin_z: int
    width: int   # X
    height: int  # Y
    depth: int   # Z
    shell_block: str
    floor_block: str
    ceiling_block: str
    details: list
    mobs: list
    loot_chests: list
    # Building features carried from blueprint
    roof_type: str = "none"
    num_floors: int = 1
    has_windows: bool = False
    has_door: bool = False
    exterior_type: str = "none"


class PlacedCorridor(BaseModel):
    """A corridor/path connecting two rooms with absolute world coordinates."""
    origin_x: int
    origin_y: int
    origin_z: int
    width: int
    height: int
    length: int  # Z extent
    block: str
    is_path: bool = False
    # L-shaped corridor support
    has_bend: bool = False
    bend_z: int = 0
    bend_dir: int = 0
    bend_length: int = 0
    # Y-offset support
    y_offset: int = 0


class PlacedBlueprint(BaseModel):
    """Blueprint with all coordinates resolved to absolute world positions."""
    name: str
    structure_type: str = "dungeon"
    karma_tier: str = "neutral"
    rooms: list[PlacedRoom]
    corridors: list[PlacedCorridor]


def _convert_room_contents(room: Room, origin_x: int, origin_y: int, origin_z: int) -> tuple[list, list, list]:
    """Convert relative detail/mob/chest coordinates to absolute."""
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

    return abs_details, abs_mobs, abs_chests


def _make_placed_room(room: Room, origin_x: int, origin_y: int, origin_z: int) -> PlacedRoom:
    """Create a PlacedRoom with absolute coordinates."""
    abs_details, abs_mobs, abs_chests = _convert_room_contents(room, origin_x, origin_y, origin_z)
    return PlacedRoom(
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
        roof_type=room.roof_type,
        num_floors=room.num_floors,
        has_windows=room.has_windows,
        has_door=room.has_door,
        exterior_type=room.exterior_type,
    )


# ---------------------------------------------------------------------------
# Layout strategies
# ---------------------------------------------------------------------------

def _layout_linear(
    blueprint: Blueprint, player_x: int, player_y: int, player_z: int,
) -> tuple[list[PlacedRoom], list[PlacedCorridor]]:
    """Classic linear chain along +Z: Room -> Corridor -> Room -> ..."""
    placed_rooms: list[PlacedRoom] = []
    placed_corridors: list[PlacedCorridor] = []

    current_z = player_z + 5
    current_x = player_x
    current_y = player_y
    prev_center_x = current_x
    prev_floor_y = current_y

    for i, room in enumerate(blueprint.rooms):
        if i > 0:
            current_x += random.randint(-4, 4)
            current_y += random.choice([-2, -1, 0, 0, 0, 1, 2])

        origin_x = current_x - room.width // 2
        origin_y = current_y
        origin_z = current_z

        placed_rooms.append(_make_placed_room(room, origin_x, origin_y, origin_z))
        current_z += room.depth

        if i < len(blueprint.corridors):
            corridor = blueprint.corridors[i]
            x_diff = current_x - prev_center_x
            y_diff = current_y - prev_floor_y

            cor_origin_x = prev_center_x - corridor.width // 2
            cor_origin_y = min(prev_floor_y, current_y)
            cor_origin_z = current_z

            has_bend = abs(x_diff) > 1
            bend_z = cor_origin_z + corridor.length // 2 if has_bend else 0
            bend_dir = (1 if x_diff > 0 else -1) if has_bend else 0
            bend_length = abs(x_diff) if has_bend else 0

            placed_corridors.append(PlacedCorridor(
                origin_x=cor_origin_x,
                origin_y=cor_origin_y,
                origin_z=cor_origin_z,
                width=corridor.width,
                height=corridor.height,
                length=corridor.length,
                block=corridor.block,
                is_path=corridor.is_path,
                has_bend=has_bend,
                bend_z=bend_z,
                bend_dir=bend_dir,
                bend_length=bend_length,
                y_offset=y_diff,
            ))
            current_z += corridor.length

        prev_center_x = current_x
        prev_floor_y = current_y

    return placed_rooms, placed_corridors


def _layout_grid(
    blueprint: Blueprint, player_x: int, player_y: int, player_z: int,
) -> tuple[list[PlacedRoom], list[PlacedCorridor]]:
    """Grid layout for villages: buildings arranged in rows/columns with paths.

    Creates a grid with spacing between buildings. Paths connect adjacent
    buildings in the grid.
    """
    placed_rooms: list[PlacedRoom] = []
    placed_corridors: list[PlacedCorridor] = []

    rooms = blueprint.rooms
    n = len(rooms)

    # Calculate grid dimensions
    cols = max(1, math.ceil(math.sqrt(n)))
    rows = max(1, math.ceil(n / cols))

    # Spacing between buildings (gap for paths)
    gap = 8

    # Place buildings in the grid
    positions: list[tuple[int, int, int]] = []
    for i, room in enumerate(rooms):
        row = i // cols
        col = i % cols

        # Calculate position with some randomness
        base_x = player_x + col * (room.width + gap) - (cols * (room.width + gap)) // 2
        base_z = player_z + 5 + row * (room.depth + gap)

        # Small random offset for organic feel
        offset_x = random.randint(-2, 2)
        offset_z = random.randint(-2, 2)

        origin_x = base_x + offset_x
        origin_y = player_y
        origin_z = base_z + offset_z

        placed_rooms.append(_make_placed_room(room, origin_x, origin_y, origin_z))
        positions.append((origin_x + room.width // 2, origin_y, origin_z + room.depth // 2))

    # Connect adjacent buildings in the grid with paths
    corridor_idx = 0
    for i in range(n - 1):
        if corridor_idx >= len(blueprint.corridors):
            break

        # Connect to the next building in sequence
        j = i + 1
        corridor = blueprint.corridors[corridor_idx]
        corridor_idx += 1

        # Calculate path between buildings
        room_a = placed_rooms[i]
        room_b = placed_rooms[j]

        # Path goes from +Z edge of room A toward room B
        path_z_start = room_a.origin_z + room_a.depth
        path_z_end = room_b.origin_z
        path_length = max(3, path_z_end - path_z_start)

        x_diff = (room_b.origin_x + room_b.width // 2) - (room_a.origin_x + room_a.width // 2)

        cor_x = room_a.origin_x + room_a.width // 2 - corridor.width // 2

        has_bend = abs(x_diff) > 2
        placed_corridors.append(PlacedCorridor(
            origin_x=cor_x,
            origin_y=player_y,
            origin_z=path_z_start,
            width=corridor.width,
            height=corridor.height,
            length=min(20, max(3, path_length)),
            block=corridor.block,
            is_path=True,
            has_bend=has_bend,
            bend_z=path_z_start + path_length // 2 if has_bend else 0,
            bend_dir=(1 if x_diff > 0 else -1) if has_bend else 0,
            bend_length=min(15, abs(x_diff)) if has_bend else 0,
            y_offset=0,
        ))

    return placed_rooms, placed_corridors


def _layout_circular(
    blueprint: Blueprint, player_x: int, player_y: int, player_z: int,
) -> tuple[list[PlacedRoom], list[PlacedCorridor]]:
    """Circular layout: buildings arranged in a ring around a center point.

    Great for temples, marketplaces, fortified compounds, etc.
    """
    placed_rooms: list[PlacedRoom] = []
    placed_corridors: list[PlacedCorridor] = []

    rooms = blueprint.rooms
    n = len(rooms)

    # Calculate ring radius based on building sizes
    avg_size = sum(max(r.width, r.depth) for r in rooms) / n if n > 0 else 10
    radius = max(15, int(avg_size * n / (2 * math.pi) + avg_size))

    center_x = player_x
    center_z = player_z + radius + 10

    positions: list[tuple[int, int]] = []
    for i, room in enumerate(rooms):
        angle = 2 * math.pi * i / n
        bx = center_x + int(radius * math.cos(angle)) - room.width // 2
        bz = center_z + int(radius * math.sin(angle)) - room.depth // 2

        placed_rooms.append(_make_placed_room(room, bx, player_y, bz))
        positions.append((bx + room.width // 2, bz + room.depth // 2))

    # Connect adjacent buildings around the ring
    corridor_idx = 0
    for i in range(n - 1):
        if corridor_idx >= len(blueprint.corridors):
            break

        corridor = blueprint.corridors[corridor_idx]
        corridor_idx += 1

        room_a = placed_rooms[i]
        room_b = placed_rooms[i + 1]

        ax = room_a.origin_x + room_a.width // 2
        az = room_a.origin_z + room_a.depth // 2
        bx = room_b.origin_x + room_b.width // 2
        bz = room_b.origin_z + room_b.depth // 2

        # Path connects in Z direction primarily
        z_start = min(az, bz) + max(room_a.depth, room_b.depth) // 2
        z_end = max(az, bz) - max(room_a.depth, room_b.depth) // 2
        path_length = max(3, min(20, abs(z_end - z_start)))

        x_diff = bx - ax

        placed_corridors.append(PlacedCorridor(
            origin_x=min(ax, bx) - corridor.width // 2,
            origin_y=player_y,
            origin_z=min(z_start, z_end),
            width=corridor.width,
            height=corridor.height,
            length=path_length,
            block=corridor.block,
            is_path=True,
            has_bend=abs(x_diff) > 2,
            bend_z=min(z_start, z_end) + path_length // 2 if abs(x_diff) > 2 else 0,
            bend_dir=(1 if x_diff > 0 else -1) if abs(x_diff) > 2 else 0,
            bend_length=min(15, abs(x_diff)) if abs(x_diff) > 2 else 0,
            y_offset=0,
        ))

    return placed_rooms, placed_corridors


def _layout_cluster(
    blueprint: Blueprint, player_x: int, player_y: int, player_z: int,
) -> tuple[list[PlacedRoom], list[PlacedCorridor]]:
    """Organic cluster layout: buildings placed with irregular spacing.

    Produces a natural, unplanned settlement feel with buildings at
    random angles and distances from each other.
    """
    placed_rooms: list[PlacedRoom] = []
    placed_corridors: list[PlacedCorridor] = []

    rooms = blueprint.rooms
    n = len(rooms)

    # Place first building near the player
    positions: list[tuple[int, int]] = []
    first_x = player_x - rooms[0].width // 2
    first_z = player_z + 5

    placed_rooms.append(_make_placed_room(rooms[0], first_x, player_y, first_z))
    positions.append((first_x + rooms[0].width // 2, first_z + rooms[0].depth // 2))

    # Place subsequent buildings at random offsets from previous buildings
    for i in range(1, n):
        room = rooms[i]

        # Pick a random existing building to cluster near
        ref_idx = random.randint(0, len(positions) - 1)
        ref_x, ref_z = positions[ref_idx]

        # Random angle and distance
        angle = random.uniform(0, 2 * math.pi)
        dist = random.randint(room.width + 5, room.width + 15)

        new_x = ref_x + int(dist * math.cos(angle)) - room.width // 2
        new_z = ref_z + int(dist * math.sin(angle)) - room.depth // 2

        placed_rooms.append(_make_placed_room(room, new_x, player_y, new_z))
        positions.append((new_x + room.width // 2, new_z + room.depth // 2))

    # Connect buildings with paths in sequence
    corridor_idx = 0
    for i in range(n - 1):
        if corridor_idx >= len(blueprint.corridors):
            break

        corridor = blueprint.corridors[corridor_idx]
        corridor_idx += 1

        room_a = placed_rooms[i]
        room_b = placed_rooms[i + 1]

        ax = room_a.origin_x + room_a.width // 2
        az = room_a.origin_z + room_a.depth
        bz = room_b.origin_z

        path_z_start = min(az, bz)
        path_z_end = max(az, bz)
        path_length = max(3, min(20, path_z_end - path_z_start))

        x_diff = (room_b.origin_x + room_b.width // 2) - ax

        placed_corridors.append(PlacedCorridor(
            origin_x=ax - corridor.width // 2,
            origin_y=player_y,
            origin_z=path_z_start,
            width=corridor.width,
            height=corridor.height,
            length=path_length,
            block=corridor.block,
            is_path=True,
            has_bend=abs(x_diff) > 2,
            bend_z=path_z_start + path_length // 2 if abs(x_diff) > 2 else 0,
            bend_dir=(1 if x_diff > 0 else -1) if abs(x_diff) > 2 else 0,
            bend_length=min(15, abs(x_diff)) if abs(x_diff) > 2 else 0,
            y_offset=0,
        ))

    return placed_rooms, placed_corridors


# ---------------------------------------------------------------------------
# Layout selection
# ---------------------------------------------------------------------------

# Structure type -> preferred layouts
_STRUCTURE_LAYOUTS: dict[str, list[str]] = {
    "dungeon":      ["linear"],
    "village":      ["grid", "cluster"],
    "castle":       ["linear", "circular"],
    "tower":        ["single", "linear"],
    "house":        ["single"],
    "temple":       ["circular", "linear"],
    "marketplace":  ["grid", "circular"],
    "fort":         ["circular", "linear"],
    "treehouse":    ["cluster"],
    "ship":         ["single", "linear"],
    "ruins":        ["cluster", "linear"],
    "cathedral":    ["single", "linear"],
    "mansion":      ["linear"],
    "tavern":       ["single"],
    "farm":         ["grid", "cluster"],
    "lighthouse":   ["single"],
    "bridge":       ["linear"],
    "arena":        ["single", "circular"],
    "library":      ["single", "linear"],
    "prison":       ["linear"],
    "mine":         ["linear"],
    "outpost":      ["cluster", "circular"],
    "monument":     ["single", "circular"],
}


def _select_layout(blueprint: Blueprint) -> str:
    """Select the best layout strategy based on structure type and room count."""
    n_rooms = len(blueprint.rooms)

    # If blueprint specifies a valid layout, respect it
    if blueprint.layout != "linear" and blueprint.layout in {"grid", "circular", "cluster", "single"}:
        if blueprint.layout == "single" and n_rooms > 1:
            return "linear"
        return blueprint.layout

    # Auto-select based on structure type
    preferred = _STRUCTURE_LAYOUTS.get(blueprint.structure_type, ["linear"])

    # Single room -> single layout
    if n_rooms == 1:
        return "single"

    # Filter out "single" for multi-room
    options = [l for l in preferred if l != "single"]
    if not options:
        options = ["linear"]

    return random.choice(options)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def solve_placement(
    blueprint: Blueprint, player_x: int, player_y: int, player_z: int,
    karma_tier: str = "neutral",
) -> PlacedBlueprint:
    """Place rooms using the appropriate layout strategy.

    The layout is chosen based on the blueprint's structure_type and
    number of rooms. Returns a PlacedBlueprint with all world coordinates
    resolved.
    """
    layout = _select_layout(blueprint)

    if layout == "single":
        # Single building — center it on the player
        room = blueprint.rooms[0]
        origin_x = player_x - room.width // 2
        origin_z = player_z + 5
        placed_room = _make_placed_room(room, origin_x, player_y, origin_z)
        placed_rooms = [placed_room]
        placed_corridors: list[PlacedCorridor] = []
    elif layout == "grid":
        placed_rooms, placed_corridors = _layout_grid(blueprint, player_x, player_y, player_z)
    elif layout == "circular":
        placed_rooms, placed_corridors = _layout_circular(blueprint, player_x, player_y, player_z)
    elif layout == "cluster":
        placed_rooms, placed_corridors = _layout_cluster(blueprint, player_x, player_y, player_z)
    else:
        placed_rooms, placed_corridors = _layout_linear(blueprint, player_x, player_y, player_z)

    return PlacedBlueprint(
        name=blueprint.name,
        structure_type=blueprint.structure_type,
        karma_tier=karma_tier,
        rooms=placed_rooms,
        corridors=placed_corridors,
    )
