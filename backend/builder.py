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

    # -- architectural style system -------------------------------------------

    def _pick_style(self, room: PlacedRoom) -> str:
        """Pick an architectural style based on room dimensions."""
        import random
        w, h, d = room.width, room.height, room.depth
        area = w * d

        styles = []
        if area >= 150 and h >= 7:
            styles.append("cathedral")
        if area >= 100:
            styles.extend(["grand_hall", "arena", "fortress"])
        if area < 120:
            styles.extend(["catacomb", "ruins"])
        if h >= 8:
            styles.append("cathedral")

        styles = styles or ["grand_hall"]
        return random.choice(styles)

    def _apply_style(self, room: PlacedRoom, style: str) -> None:
        """Apply an architectural style to a room."""
        logger.info("Applying '%s' style to room '%s'", style, room.name)
        if style == "grand_hall":
            self._style_grand_hall(room)
        elif style == "arena":
            self._style_arena(room)
        elif style == "catacomb":
            self._style_catacomb(room)
        elif style == "cathedral":
            self._style_cathedral(room)
        elif style == "fortress":
            self._style_fortress(room)
        elif style == "ruins":
            self._style_ruins(room)

    def _style_grand_hall(self, room: PlacedRoom) -> None:
        """Grand Hall: symmetrical pillars, floor border, ceiling trim."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        pb = room.shell_block

        # Two rows of pillars along the length
        if w >= 8 and d >= 8:
            pillar_x = [ox + 2, ox + w - 3]
            for px in pillar_x:
                for dz in range(3, d - 2, 4):
                    for dy in range(1, h - 1):
                        self._cmd(f"/setblock {px} {oy + dy} {oz + dz} {pb} replace")

        # Floor border (double-width for grandeur)
        for x in range(ox + 1, ox + w - 1):
            self._cmd(f"/setblock {x} {oy} {oz + 1} {pb} replace")
            self._cmd(f"/setblock {x} {oy} {oz + d - 2} {pb} replace")
        for z in range(oz + 1, oz + d - 1):
            self._cmd(f"/setblock {ox + 1} {oy} {z} {pb} replace")
            self._cmd(f"/setblock {ox + w - 2} {oy} {z} {pb} replace")

        # Ceiling trim
        if h >= 5:
            trim_y = oy + h - 2
            for x in range(ox + 1, ox + w - 1):
                self._cmd(f"/setblock {x} {trim_y} {oz + 1} {pb} replace")
                self._cmd(f"/setblock {x} {trim_y} {oz + d - 2} {pb} replace")

    def _style_arena(self, room: PlacedRoom) -> None:
        """Arena: sunken center pit, raised perimeter, optional lava/water moat."""
        import random
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Raised 1-block perimeter walkway
        for x in range(ox + 1, ox + w - 1):
            for z in [oz + 1, oz + 2, oz + d - 2, oz + d - 3]:
                self._cmd(f"/setblock {x} {oy + 1} {z} {room.floor_block} replace")
        for z in range(oz + 1, oz + d - 1):
            for x in [ox + 1, ox + 2, ox + w - 2, ox + w - 3]:
                self._cmd(f"/setblock {x} {oy + 1} {z} {room.floor_block} replace")

        # Inner moat ring (1 block lower than floor)
        moat_block = random.choice(["minecraft:water", "minecraft:lava", "minecraft:magma_block"])
        if w >= 10 and d >= 10:
            for x in range(ox + 3, ox + w - 3):
                self._cmd(f"/setblock {x} {oy} {oz + 3} {moat_block} replace")
                self._cmd(f"/setblock {x} {oy} {oz + d - 4} {moat_block} replace")
            for z in range(oz + 3, oz + d - 3):
                self._cmd(f"/setblock {ox + 3} {oy} {z} {moat_block} replace")
                self._cmd(f"/setblock {ox + w - 4} {oy} {z} {moat_block} replace")

        # Corner posts (short pillars on the raised perimeter)
        for cx, cz in [(ox + 1, oz + 1), (ox + w - 2, oz + 1),
                        (ox + 1, oz + d - 2), (ox + w - 2, oz + d - 2)]:
            for dy in range(1, min(4, h - 1)):
                self._cmd(f"/setblock {cx} {oy + dy} {cz} {room.shell_block} replace")

    def _style_catacomb(self, room: PlacedRoom) -> None:
        """Catacomb: alcoves carved into walls, low arched ceiling simulation."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Wall alcoves (niches every 3 blocks along Z walls)
        if w >= 7:
            for dz in range(2, d - 2, 3):
                # Left wall alcove — push wall in 1 block
                self._cmd(f"/setblock {ox} {oy + 1} {oz + dz} minecraft:air replace")
                self._cmd(f"/setblock {ox} {oy + 2} {oz + dz} minecraft:air replace")
                # Right wall alcove
                self._cmd(f"/setblock {ox + w - 1} {oy + 1} {oz + dz} minecraft:air replace")
                self._cmd(f"/setblock {ox + w - 1} {oy + 2} {oz + dz} minecraft:air replace")

        # Low arch ceiling — fill top row leaving center open
        if h >= 5:
            arch_y = oy + h - 2
            for x in [ox + 1, ox + w - 2]:
                for z in range(oz + 1, oz + d - 1):
                    self._cmd(f"/setblock {x} {arch_y} {z} {room.shell_block} replace")

        # Scattered floor bones
        import random
        bone_blocks = ["minecraft:bone_block", "minecraft:cobweb"]
        for _ in range(min(5, (w * d) // 20)):
            bx = random.randint(ox + 2, ox + w - 3)
            bz = random.randint(oz + 2, oz + d - 3)
            self._cmd(f"/setblock {bx} {oy + 1} {bz} {random.choice(bone_blocks)} replace")

    def _style_cathedral(self, room: PlacedRoom) -> None:
        """Cathedral: stepped/vaulted ceiling, tall columns, stained glass effect."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Stepped ceiling — each ring inward goes 1 block higher
        max_steps = min(3, (w - 4) // 2, (d - 4) // 2, h - 3)
        for step in range(max_steps):
            step_y = oy + h - 2 - step
            sx1 = ox + 1 + step
            sx2 = ox + w - 2 - step
            sz1 = oz + 1 + step
            sz2 = oz + d - 2 - step
            if sx1 < sx2 and sz1 < sz2:
                for x in range(sx1, sx2 + 1):
                    self._cmd(f"/setblock {x} {step_y} {sz1} {room.ceiling_block} replace")
                    self._cmd(f"/setblock {x} {step_y} {sz2} {room.ceiling_block} replace")
                for z in range(sz1, sz2 + 1):
                    self._cmd(f"/setblock {sx1} {step_y} {z} {room.ceiling_block} replace")
                    self._cmd(f"/setblock {sx2} {step_y} {z} {room.ceiling_block} replace")

        # Tall thin columns
        if d >= 10:
            for dz in range(2, d - 2, 5):
                for dy in range(1, h - 1):
                    self._cmd(f"/setblock {ox + 2} {oy + dy} {oz + dz} {room.shell_block} replace")
                    self._cmd(f"/setblock {ox + w - 3} {oy + dy} {oz + dz} {room.shell_block} replace")

        # Stained glass windows in walls (using colored stained glass)
        import random
        glass_colors = ["minecraft:red_stained_glass", "minecraft:blue_stained_glass",
                        "minecraft:purple_stained_glass", "minecraft:yellow_stained_glass",
                        "minecraft:cyan_stained_glass"]
        if h >= 6:
            for dz in range(3, d - 2, 4):
                glass = random.choice(glass_colors)
                for dy in range(3, min(h - 2, 6)):
                    self._cmd(f"/setblock {ox} {oy + dy} {oz + dz} {glass} replace")
                    self._cmd(f"/setblock {ox + w - 1} {oy + dy} {oz + dz} {glass} replace")

    def _style_fortress(self, room: PlacedRoom) -> None:
        """Fortress: thick buttresses, arrow slits, exterior battlements."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        pb = room.shell_block

        # Buttresses — thick L-shaped supports along walls every 4 blocks
        for dz in range(1, d - 1, 4):
            # Left wall buttresses (2 blocks thick, full height)
            for dy in range(1, h - 1):
                self._cmd(f"/setblock {ox + 1} {oy + dy} {oz + dz} {pb} replace")
            # Right wall buttresses
            for dy in range(1, h - 1):
                self._cmd(f"/setblock {ox + w - 2} {oy + dy} {oz + dz} {pb} replace")

        # Arrow slits (iron bars in walls between buttresses)
        if h >= 5:
            for dz in range(3, d - 2, 4):
                for dy in range(2, min(h - 2, 5)):
                    self._cmd(f"/setblock {ox} {oy + dy} {oz + dz} minecraft:iron_bars replace")
                    self._cmd(f"/setblock {ox + w - 1} {oy + dy} {oz + dz} minecraft:iron_bars replace")

        # Battlements on top (raised merlons along the ceiling edge)
        top_y = oy + h - 1
        for x in range(ox, ox + w, 2):
            self._cmd(f"/setblock {x} {top_y + 1} {oz} {pb} replace")
            self._cmd(f"/setblock {x} {top_y + 1} {oz + d - 1} {pb} replace")

    def _style_ruins(self, room: PlacedRoom) -> None:
        """Ruins: partially destroyed walls, overgrown vegetation, crumbled ceiling."""
        import random
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Punch random holes in walls (decay effect)
        num_holes = max(3, (w + d) // 3)
        for _ in range(num_holes):
            side = random.choice(["x_min", "x_max", "z_min", "z_max"])
            dy = random.randint(1, h - 2)
            if side == "x_min":
                dz = random.randint(1, d - 2)
                self._cmd(f"/setblock {ox} {oy + dy} {oz + dz} minecraft:air replace")
            elif side == "x_max":
                dz = random.randint(1, d - 2)
                self._cmd(f"/setblock {ox + w - 1} {oy + dy} {oz + dz} minecraft:air replace")
            elif side == "z_min":
                dx = random.randint(1, w - 2)
                self._cmd(f"/setblock {ox + dx} {oy + dy} {oz} minecraft:air replace")
            else:
                dx = random.randint(1, w - 2)
                self._cmd(f"/setblock {ox + dx} {oy + dy} {oz + d - 1} minecraft:air replace")

        # Overgrown vegetation
        veg_blocks = ["minecraft:moss_block", "minecraft:moss_carpet",
                      "minecraft:cobweb", "minecraft:vine"]
        for _ in range(min(8, (w * d) // 15)):
            bx = random.randint(ox + 1, ox + w - 2)
            bz = random.randint(oz + 1, oz + d - 2)
            self._cmd(f"/setblock {bx} {oy + 1} {bz} {random.choice(veg_blocks)} replace")

        # Crumbled ceiling patches
        for _ in range(min(4, (w * d) // 30)):
            cx = random.randint(ox + 2, ox + w - 3)
            cz = random.randint(oz + 2, oz + d - 3)
            self._cmd(f"/setblock {cx} {oy + h - 1} {cz} minecraft:air replace")
            # Debris on floor below
            self._cmd(f"/setblock {cx} {oy + 1} {cz} minecraft:cobblestone replace")

        # Cracked/mossy variant of shell block on remaining walls
        mossy_map = {
            "minecraft:stone_bricks": "minecraft:mossy_stone_bricks",
            "minecraft:cobblestone": "minecraft:mossy_cobblestone",
            "minecraft:deepslate_bricks": "minecraft:cracked_deepslate_bricks",
        }
        mossy = mossy_map.get(room.shell_block, "minecraft:cracked_stone_bricks")
        for _ in range(min(10, (w + d))):
            side = random.choice(["x_min", "x_max", "z_min", "z_max"])
            dy = random.randint(1, h - 2)
            if side == "x_min":
                dz = random.randint(1, d - 2)
                self._cmd(f"/setblock {ox} {oy + dy} {oz + dz} {mossy} replace")
            elif side == "x_max":
                dz = random.randint(1, d - 2)
                self._cmd(f"/setblock {ox + w - 1} {oy + dy} {oz + dz} {mossy} replace")
            elif side == "z_min":
                dx = random.randint(1, w - 2)
                self._cmd(f"/setblock {ox + dx} {oy + dy} {oz} {mossy} replace")
            else:
                dx = random.randint(1, w - 2)
                self._cmd(f"/setblock {ox + dx} {oy + dy} {oz + d - 1} {mossy} replace")

    # -- entrance carving ----------------------------------------------------

    def _enhance_room_entrance(self, room: PlacedRoom) -> None:
        """Carve an arched entrance in the +Z wall (where corridor connects)."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Entrance centered on +Z wall
        mid_x = ox + w // 2
        entrance_z = oz + d - 1  # the +Z wall

        # Carve a 3-wide, (h-2)-tall opening
        for dx in range(-1, 2):
            for dy in range(1, min(h - 1, 4)):
                self._cmd(f"/setblock {mid_x + dx} {oy + dy} {entrance_z} minecraft:air replace")

        # Add arch block above entrance
        if h >= 5:
            self._cmd(f"/setblock {mid_x - 1} {oy + min(h - 1, 4)} {entrance_z} {room.shell_block} replace")
            self._cmd(f"/setblock {mid_x + 1} {oy + min(h - 1, 4)} {entrance_z} {room.shell_block} replace")

    def _enhance_room_back_entrance(self, room: PlacedRoom) -> None:
        """Carve an entrance in the -Z wall (where previous corridor connects)."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h = room.width, room.height

        mid_x = ox + w // 2
        entrance_z = oz  # the -Z wall

        for dx in range(-1, 2):
            for dy in range(1, min(h - 1, 4)):
                self._cmd(f"/setblock {mid_x + dx} {oy + dy} {entrance_z} minecraft:air replace")

        if h >= 5:
            self._cmd(f"/setblock {mid_x - 1} {oy + min(h - 1, 4)} {entrance_z} {room.shell_block} replace")
            self._cmd(f"/setblock {mid_x + 1} {oy + min(h - 1, 4)} {entrance_z} {room.shell_block} replace")

    def _enhance_corridor_lighting(self, corridor: PlacedCorridor) -> None:
        """Place lanterns along the corridor ceiling at intervals."""
        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, h, length = corridor.width, corridor.height, corridor.length

        mid_x = ox + w // 2
        light_y = oy + h - 2  # just below ceiling

        # Place a lantern every 3 blocks along the corridor
        for dz in range(2, length - 1, 3):
            self._cmd(f"/setblock {mid_x} {light_y} {oz + dz} minecraft:chain replace")
            if light_y - 1 > oy:
                self._cmd(f"/setblock {mid_x} {light_y - 1} {oz + dz} minecraft:lantern replace")

    def _enhance_corridor_floor(self, corridor: PlacedCorridor) -> None:
        """Add a contrasting floor strip down the center of corridors."""
        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, length = corridor.width, corridor.length

        mid_x = ox + w // 2
        # Place a contrasting block strip down the center
        for dz in range(1, length - 1):
            self._cmd(f"/setblock {mid_x} {oy} {oz + dz} {corridor.block} replace")

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

    # -- shape variations ----------------------------------------------------

    def _shape_L(self, room: PlacedRoom) -> None:
        """Carve out a corner to make the room L-shaped."""
        import random
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        
        # Carve out one of the front corners (to not break the entrance/exit at mid Z walls)
        cut_w = w // 2 - 1
        cut_d = d // 2 - 1
        
        left_corner = random.choice([True, False])
        if left_corner:
            cx1, cx2 = ox, ox + cut_w
        else:
            cx1, cx2 = ox + w - cut_w, ox + w - 1
            
        cz1, cz2 = oz + d - cut_d, oz + d - 1  # Carve the +Z corners so previous -Z entrance is safe

        # Erase that corner completely
        for cmd in _chunked_fills(cx1, oy, cz1, cx2, oy + h - 1, cz2, "minecraft:air"):
            self._cmd(cmd)

        # Build new inner wall to seal it
        if left_corner:
            # Wall along +X face of cut, and -Z face of cut
            for cmd in _chunked_fills(cx2, oy, cz1, cx2, oy + h - 1, cz2, room.shell_block):
                self._cmd(cmd)
            for cmd in _chunked_fills(cx1, oy, cz1, cx2, oy + h - 1, cz1, room.shell_block):
                self._cmd(cmd)
        else:
            for cmd in _chunked_fills(cx1, oy, cz1, cx1, oy + h - 1, cz2, room.shell_block):
                self._cmd(cmd)
            for cmd in _chunked_fills(cx1, oy, cz1, cx2, oy + h - 1, cz1, room.shell_block):
                self._cmd(cmd)

        logger.info("Applied L-shape to room '%s'", room.name)

    def _shape_T(self, room: PlacedRoom) -> None:
        """Carve out two front corners to make the room T-shaped."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        
        # Leave a central shaft, carve out both front left and front right corners
        shaft_w = max(5, w // 3)
        cut_w = (w - shaft_w) // 2
        cut_d = d // 2 - 1
        
        # Left cut: x=[0, cut_w], z=[d-cut_d, d]
        for cmd in _chunked_fills(ox, oy, oz + d - cut_d, ox + cut_w, oy + h - 1, oz + d - 1, "minecraft:air"):
            self._cmd(cmd)
        # Seal left cut
        for cmd in _chunked_fills(ox + cut_w, oy, oz + d - cut_d, ox + cut_w, oy + h - 1, oz + d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox, oy, oz + d - cut_d, ox + cut_w, oy + h - 1, oz + d - cut_d, room.shell_block):
            self._cmd(cmd)

        # Right cut: x=[w-cut_w, w], z=[d-cut_d, d]
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz + d - cut_d, ox + w - 1, oy + h - 1, oz + d - 1, "minecraft:air"):
            self._cmd(cmd)
        # Seal right cut
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz + d - cut_d, ox + w - cut_w, oy + h - 1, oz + d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz + d - cut_d, ox + w - 1, oy + h - 1, oz + d - cut_d, room.shell_block):
            self._cmd(cmd)

        logger.info("Applied T-shape to room '%s'", room.name)

    def _shape_circle(self, room: PlacedRoom) -> None:
        """Carve the rectangular room into a cylinder."""
        import math
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        cx = ox + w / 2.0
        cz = oz + d / 2.0
        radius = min(w, d) / 2.0

        for x in range(ox, ox + w):
            for z in range(oz, oz + d):
                dist = math.hypot(x + 0.5 - cx, z + 0.5 - cz)
                
                # If outside the circle bounds entirely, delete it
                if dist > radius:
                    self._cmd(f"/fill {x} {oy} {z} {x} {oy + h - 1} {z} minecraft:air replace")
                # If just inside the bounds, it's the new curved wall
                elif dist > radius - 1.5:
                    self._cmd(f"/fill {x} {oy} {z} {x} {oy + h - 1} {z} {room.shell_block} replace")
        
        logger.info("Applied circle shape to room '%s'", room.name)

    # -- high-level build orchestration --------------------------------------

    def _build_room(self, room: PlacedRoom, room_index: int = 0,
                    total_rooms: int = 1) -> None:
        """Execute all build phases for a single room, with style-based enhancements."""
        # Core structure
        self._build_room_shell(room)
        self._build_room_floor(room)
        self._build_room_ceiling(room)
        self._carve_room_interior(room)

        # Apply shape variation (L-shape, T-shape, circle)
        import random
        shape = random.choice(["rectangle", "rectangle", "L-shape", "T-shape", "circle", "circle"])
        if shape == "L-shape" and room.width >= 10 and room.depth >= 10:
            self._shape_L(room)
        elif shape == "T-shape" and room.width >= 12 and room.depth >= 10:
            self._shape_T(room)
        elif shape == "circle" and room.width >= 8 and room.depth >= 8:
            self._shape_circle(room)

        # Pick and apply a random architectural style
        style = self._pick_style(room)
        self._apply_style(room, style)

        # Carve entrances between rooms and corridors
        if room_index < total_rooms - 1:
            self._enhance_room_entrance(room)
        if room_index > 0:
            self._enhance_room_back_entrance(room)

        # AI-generated content (placed LAST so it overrides style blocks)
        self._place_room_details(room)
        self._spawn_room_mobs(room)
        self._place_room_loot_chests(room)

    def _build_corridor(self, corridor: PlacedCorridor) -> None:
        """Execute all build phases for a single corridor, with enhancements."""
        self._build_corridor_shell(corridor)
        self._carve_corridor_interior(corridor)
        self._open_corridor_ends(corridor)
        # Enhancements
        self._enhance_corridor_lighting(corridor)
        self._enhance_corridor_floor(corridor)

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
                self._build_room(room, room_index=idx - 1, total_rooms=total_rooms)
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
