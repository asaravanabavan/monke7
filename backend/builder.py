"""
RCON executor — builds placed dungeon blueprints in a Minecraft world.

Uses the ``mctools`` library to send ``/fill``, ``/setblock``, ``/summon``,
``/data merge``, and ``/tellraw`` commands over RCON.  Large fills are
automatically chunked to stay within the 32 768-block server limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import mctools

from backend.config import settings
from backend.placer import PlacedBlueprint, PlacedRoom, PlacedCorridor

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Minecraft /fill can place at most 32 768 blocks per command.
_FILL_BLOCK_LIMIT = 32_768


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunked_fills(
    x1: int, y1: int, z1: int,
    x2: int, y2: int, z2: int,
    block: str,
) -> list[str]:
    """Return one or more ``/fill`` commands that cover the given volume.

    If the total number of blocks exceeds :data:`_FILL_BLOCK_LIMIT`, the
    volume is split into smaller slabs along the longest axis.
    """
    dx = abs(x2 - x1) + 1
    dy = abs(y2 - y1) + 1
    dz = abs(z2 - z1) + 1
    volume = dx * dy * dz

    if volume <= _FILL_BLOCK_LIMIT:
        return [f"/fill {x1} {y1} {z1} {x2} {y2} {z2} {block}"]

    # Split along the longest axis.
    commands: list[str] = []

    if dx >= dy and dx >= dz:
        # Split along X
        mid_x = (x1 + x2) // 2
        commands.extend(_chunked_fills(x1, y1, z1, mid_x, y2, z2, block))
        commands.extend(_chunked_fills(mid_x + 1, y1, z1, x2, y2, z2, block))
    elif dy >= dx and dy >= dz:
        # Split along Y
        mid_y = (y1 + y2) // 2
        commands.extend(_chunked_fills(x1, y1, z1, x2, mid_y, z2, block))
        commands.extend(_chunked_fills(x1, mid_y + 1, z1, x2, y2, z2, block))
    else:
        # Split along Z
        mid_z = (z1 + z2) // 2
        commands.extend(_chunked_fills(x1, y1, z1, x2, y2, mid_z, block))
        commands.extend(_chunked_fills(x1, y1, mid_z + 1, x2, y2, z2, block))

    return commands


def _chest_nbt(items: list[str]) -> str:
    """Build an NBT ``Items`` tag for a chest from a list of item IDs.

    Each item is placed in a successive slot (0-26).
    """
    entries: list[str] = []
    for slot, item_id in enumerate(items[:27]):
        entries.append(
            f'{{Slot:{slot}b,id:"{item_id}",Count:1b}}'
        )
    return "{Items:[" + ",".join(entries) + "]}"


def _tellraw(message: str, color: str = "gold") -> str:
    """Return a ``/tellraw`` command that broadcasts a coloured message."""
    # Escape inner double-quotes for the JSON payload.
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    return f'/tellraw @a {{"text":"{safe}","color":"{color}"}}'


# ---------------------------------------------------------------------------
# BuildExecutor
# ---------------------------------------------------------------------------

class BuildExecutor:
    """Sends RCON commands to build a :class:`PlacedBlueprint` in-world."""

    def __init__(self) -> None:
        self._rcon: mctools.RCONClient | None = None

    # -- connection management -----------------------------------------------

    def connect(self) -> None:
        """Open an RCON connection using the application settings."""
        self._rcon = mctools.RCONClient(
            settings.rcon_host,
            port=settings.rcon_port,
        )
        self._rcon.login(settings.rcon_password)
        logger.info(
            "RCON connected to %s:%s", settings.rcon_host, settings.rcon_port,
        )

    def disconnect(self) -> None:
        """Close the RCON connection if it is open."""
        if self._rcon is not None:
            try:
                self._rcon.stop()
            except Exception:
                logger.debug("RCON stop raised an exception", exc_info=True)
            finally:
                self._rcon = None
                logger.info("RCON disconnected")

    # -- low-level command dispatch ------------------------------------------

    def _cmd(self, command: str) -> str:
        """Send a single command and return the server response."""
        assert self._rcon is not None, "RCON is not connected"
        logger.debug("RCON> %s", command)
        response: str = self._rcon.command(command)
        return response

    # -- room build phases ---------------------------------------------------

    def _build_room_shell(self, room: PlacedRoom) -> None:
        """Phase (a): fill the entire room volume with the shell block."""
        x1 = room.origin_x
        y1 = room.origin_y
        z1 = room.origin_z
        x2 = room.origin_x + room.width - 1
        y2 = room.origin_y + room.height - 1
        z2 = room.origin_z + room.depth - 1

        for cmd in _chunked_fills(x1, y1, z1, x2, y2, z2, room.shell_block):
            self._cmd(cmd)

    def _build_room_floor(self, room: PlacedRoom) -> None:
        """Phase (b): fill the floor layer (y = origin_y) with floor_block."""
        x1 = room.origin_x
        y1 = room.origin_y
        z1 = room.origin_z
        x2 = room.origin_x + room.width - 1
        y2 = room.origin_y  # single layer
        z2 = room.origin_z + room.depth - 1

        for cmd in _chunked_fills(x1, y1, z1, x2, y2, z2, room.floor_block):
            self._cmd(cmd)

    def _build_room_ceiling(self, room: PlacedRoom) -> None:
        """Phase (c): fill the ceiling layer with ceiling_block."""
        x1 = room.origin_x
        y1 = room.origin_y + room.height - 1
        z1 = room.origin_z
        x2 = room.origin_x + room.width - 1
        y2 = room.origin_y + room.height - 1  # single layer
        z2 = room.origin_z + room.depth - 1

        for cmd in _chunked_fills(x1, y1, z1, x2, y2, z2, room.ceiling_block):
            self._cmd(cmd)

    def _carve_room_interior(self, room: PlacedRoom) -> None:
        """Phase (d): hollow out the interior with air."""
        x1 = room.origin_x + 1
        y1 = room.origin_y + 1
        z1 = room.origin_z + 1
        x2 = room.origin_x + room.width - 2
        y2 = room.origin_y + room.height - 2
        z2 = room.origin_z + room.depth - 2

        # Only carve if there is actually interior space.
        if x1 <= x2 and y1 <= y2 and z1 <= z2:
            for cmd in _chunked_fills(x1, y1, z1, x2, y2, z2, "minecraft:air"):
                self._cmd(cmd)

    def _place_room_details(self, room: PlacedRoom) -> None:
        """Phase (e): place individual detail blocks via /setblock."""
        for detail in room.details:
            block = detail["block"]
            x = detail["x"]
            y = detail["y"]
            z = detail["z"]
            self._cmd(f"/setblock {x} {y} {z} {block} replace")

    def _spawn_room_mobs(self, room: PlacedRoom) -> None:
        """Phase (f): summon mobs."""
        for mob in room.mobs:
            entity = mob["entity"]
            x = mob["x"]
            y = mob["y"]
            z = mob["z"]
            count = mob.get("count", 1)
            for _ in range(count):
                self._cmd(f"/summon {entity} {x} {y} {z}")

    def _place_room_loot_chests(self, room: PlacedRoom) -> None:
        """Phase (g): place chests and merge item NBT data."""
        for chest in room.loot_chests:
            x = chest["x"]
            y = chest["y"]
            z = chest["z"]
            items: list[str] = chest.get("items", [])

            # Place the chest block.
            self._cmd(f"/setblock {x} {y} {z} minecraft:chest replace")

            # Merge items into the chest if any are specified.
            if items:
                nbt = _chest_nbt(items)
                self._cmd(f"/data merge block {x} {y} {z} {nbt}")

    # -- corridor build phases -----------------------------------------------

    def _build_corridor_shell(self, corridor: PlacedCorridor) -> None:
        """Phase (a): fill the corridor volume with the corridor block."""
        x1 = corridor.origin_x
        y1 = corridor.origin_y
        z1 = corridor.origin_z
        x2 = corridor.origin_x + corridor.width - 1
        y2 = corridor.origin_y + corridor.height - 1
        z2 = corridor.origin_z + corridor.length - 1

        for cmd in _chunked_fills(x1, y1, z1, x2, y2, z2, corridor.block):
            self._cmd(cmd)

    def _carve_corridor_interior(self, corridor: PlacedCorridor) -> None:
        """Phase (b): hollow out the corridor interior."""
        x1 = corridor.origin_x + 1
        y1 = corridor.origin_y + 1
        z1 = corridor.origin_z + 1
        x2 = corridor.origin_x + corridor.width - 2
        y2 = corridor.origin_y + corridor.height - 2
        z2 = corridor.origin_z + corridor.length - 2

        if x1 <= x2 and y1 <= y2 and z1 <= z2:
            for cmd in _chunked_fills(x1, y1, z1, x2, y2, z2, "minecraft:air"):
                self._cmd(cmd)

    def _open_corridor_ends(self, corridor: PlacedCorridor) -> None:
        """Phase (c): carve air at both Z-ends so the corridor connects to rooms.

        Opens a 2-block-wide, full-interior-height passage at z_min and z_max
        faces of the corridor.
        """
        # Interior X range (centred within the corridor width)
        ix1 = corridor.origin_x + 1
        ix2 = corridor.origin_x + corridor.width - 2

        # Interior Y range
        iy1 = corridor.origin_y + 1
        iy2 = corridor.origin_y + corridor.height - 2

        if ix1 > ix2 or iy1 > iy2:
            return  # corridor too narrow/short to carve

        # Z-min end (the wall at origin_z)
        z_min = corridor.origin_z
        for cmd in _chunked_fills(ix1, iy1, z_min, ix2, iy2, z_min, "minecraft:air"):
            self._cmd(cmd)

        # Z-max end (the wall at origin_z + length - 1)
        z_max = corridor.origin_z + corridor.length - 1
        for cmd in _chunked_fills(ix1, iy1, z_max, ix2, iy2, z_max, "minecraft:air"):
            self._cmd(cmd)

    # -- high-level build orchestration --------------------------------------

    def _build_room(self, room: PlacedRoom) -> None:
        """Execute all build phases for a single room."""
        self._build_room_shell(room)
        self._build_room_floor(room)
        self._build_room_ceiling(room)
        self._carve_room_interior(room)
        self._place_room_details(room)
        self._spawn_room_mobs(room)
        self._place_room_loot_chests(room)

    def _build_corridor(self, corridor: PlacedCorridor) -> None:
        """Execute all build phases for a single corridor."""
        self._build_corridor_shell(corridor)
        self._carve_corridor_interior(corridor)
        self._open_corridor_ends(corridor)

    # -- public API ----------------------------------------------------------

    async def build(self, placed: PlacedBlueprint) -> dict:
        """Build all rooms and corridors from *placed* in the Minecraft world.

        Sends coloured progress messages via ``/tellraw`` and pauses between
        rooms to avoid server lag.

        Returns a summary ``dict`` with:
        - ``name``: the dungeon name
        - ``room_count``: number of rooms built
        """
        total_rooms = len(placed.rooms)
        total_corridors = len(placed.corridors)

        self.connect()
        try:
            # Announce build start.
            self._cmd(
                _tellraw(
                    f"[NemoCraft] Starting build: \"{placed.name}\" "
                    f"({total_rooms} rooms, {total_corridors} corridors)",
                    color="green",
                )
            )

            # -- Build rooms -------------------------------------------------
            for idx, room in enumerate(placed.rooms, start=1):
                self._cmd(
                    _tellraw(
                        f'[NemoCraft] Building room: "{room.name}" '
                        f"({idx}/{total_rooms})...",
                        color="gold",
                    )
                )
                self._build_room(room)
                logger.info("Built room %d/%d: %s", idx, total_rooms, room.name)

                await asyncio.sleep(settings.build_delay)

            # -- Build corridors ---------------------------------------------
            for idx, corridor in enumerate(placed.corridors, start=1):
                self._cmd(
                    _tellraw(
                        f"[NemoCraft] Building corridor ({idx}/{total_corridors})...",
                        color="gold",
                    )
                )
                self._build_corridor(corridor)
                logger.info("Built corridor %d/%d", idx, total_corridors)

                await asyncio.sleep(settings.build_delay)

            # Announce completion.
            self._cmd(
                _tellraw(
                    f'[NemoCraft] Dungeon "{placed.name}" complete!',
                    color="green",
                )
            )
            logger.info(
                "Build complete: %s (%d rooms, %d corridors)",
                placed.name,
                total_rooms,
                total_corridors,
            )

        finally:
            self.disconnect()

        return {
            "name": placed.name,
            "room_count": total_rooms,
        }
