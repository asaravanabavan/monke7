"""
RCON executor — builds placed dungeon blueprints in a Minecraft world.

Uses the ``mctools`` library to send ``/fill``, ``/setblock``, ``/summon``,
``/data merge``, and ``/tellraw`` commands over RCON.  Large fills are
automatically chunked to stay within the 32 768-block server limit.

Major systems:
- Shape variations: rectangle, L-shape, T-shape, circle, cross, octagon
- Architectural styles: grand_hall, arena, catacomb, cathedral, fortress, ruins
- Shape-style compatibility matrix (no buttresses on circles, etc.)
- Ambient room lighting system
- Floor pattern generation
- Entrance/doorway framing with arches
- Corridor variety: arched, pillared, trapped, L-shaped bends, staircases
- Themed room decoration based on AI room names
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
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
# Shape-style compatibility matrix
# ---------------------------------------------------------------------------
# Each shape lists which architectural styles work well with it.
_SHAPE_STYLE_COMPAT: dict[str, list[str]] = {
    "rectangle": ["grand_hall", "arena", "catacomb", "cathedral", "fortress", "ruins"],
    "L-shape":   ["catacomb", "ruins", "fortress"],
    "T-shape":   ["grand_hall", "fortress", "catacomb"],
    "circle":    ["arena", "cathedral", "ruins"],
    "cross":     ["cathedral", "grand_hall"],
    "octagon":   ["arena", "cathedral", "grand_hall"],
}

# Theme keyword -> decoration approach for AI room names
_ROOM_THEME_KEYWORDS: dict[str, list[str]] = {
    "throne": ["minecraft:gold_block", "minecraft:red_wool", "minecraft:lantern"],
    "library": ["minecraft:bookshelf", "minecraft:lantern", "minecraft:lectern"],
    "prison": ["minecraft:iron_bars", "minecraft:chain", "minecraft:skeleton_skull"],
    "forge": ["minecraft:blast_furnace", "minecraft:lava", "minecraft:magma_block"],
    "crypt": ["minecraft:bone_block", "minecraft:soul_lantern", "minecraft:cobweb"],
    "temple": ["minecraft:chiseled_stone_bricks", "minecraft:lantern", "minecraft:gold_block"],
    "altar": ["minecraft:enchanting_table", "minecraft:candle", "minecraft:soul_lantern"],
    "armory": ["minecraft:anvil", "minecraft:grindstone", "minecraft:iron_block"],
    "treasury": ["minecraft:gold_block", "minecraft:diamond_block", "minecraft:lantern"],
    "garden": ["minecraft:moss_block", "minecraft:moss_carpet", "minecraft:lantern"],
    "arena": ["minecraft:magma_block", "minecraft:iron_bars", "minecraft:chain"],
    "spawner": ["minecraft:spawner", "minecraft:cobweb", "minecraft:soul_torch"],
    "lava": ["minecraft:magma_block", "minecraft:lava", "minecraft:soul_lantern"],
    "water": ["minecraft:prismarine", "minecraft:sea_lantern", "minecraft:water"],
    "nether": ["minecraft:nether_bricks", "minecraft:soul_fire", "minecraft:magma_block"],
    "sanctum": ["minecraft:crying_obsidian", "minecraft:end_rod", "minecraft:candle"],
    "dungeon": ["minecraft:cobweb", "minecraft:chain", "minecraft:skeleton_skull"],
    "chamber": ["minecraft:lantern", "minecraft:chain", "minecraft:cobweb"],
    "hall": ["minecraft:lantern", "minecraft:chain", "minecraft:stone_brick_wall"],
    "gallery": ["minecraft:lantern", "minecraft:bookshelf", "minecraft:chain"],
    "pit": ["minecraft:magma_block", "minecraft:lava", "minecraft:iron_bars"],
    "lair": ["minecraft:cobweb", "minecraft:bone_block", "minecraft:soul_lantern"],
    "tomb": ["minecraft:bone_block", "minecraft:soul_lantern", "minecraft:cobweb"],
    "vault": ["minecraft:iron_block", "minecraft:iron_bars", "minecraft:lantern"],
    "lab": ["minecraft:brewing_stand", "minecraft:cauldron", "minecraft:redstone_lamp"],
}

# Floor pattern types
_FLOOR_PATTERNS = ["border", "checkered", "center_medallion", "cross_path", "plain"]

# Corridor decoration types
_CORRIDOR_STYLES = ["plain", "arched", "pillared", "trapped", "ornate"]

# Lighting blocks ordered by warmth
_WARM_LIGHTS = ["minecraft:lantern", "minecraft:torch", "minecraft:campfire",
                "minecraft:jack_o_lantern", "minecraft:redstone_lamp"]
_COLD_LIGHTS = ["minecraft:soul_lantern", "minecraft:soul_torch",
                "minecraft:soul_campfire", "minecraft:end_rod", "minecraft:sea_lantern"]


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
        mid_x = (x1 + x2) // 2
        commands.extend(_chunked_fills(x1, y1, z1, mid_x, y2, z2, block))
        commands.extend(_chunked_fills(mid_x + 1, y1, z1, x2, y2, z2, block))
    elif dy >= dx and dy >= dz:
        mid_y = (y1 + y2) // 2
        commands.extend(_chunked_fills(x1, y1, z1, x2, mid_y, z2, block))
        commands.extend(_chunked_fills(x1, mid_y + 1, z1, x2, y2, z2, block))
    else:
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
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    return f'/tellraw @a {{"text":"{safe}","color":"{color}"}}'


def _detect_room_theme(room_name: str) -> str | None:
    """Detect a theme keyword from the room's AI-given name."""
    lower = room_name.lower()
    for keyword in _ROOM_THEME_KEYWORDS:
        if keyword in lower:
            return keyword
    return None


def _pick_light_block(shell_block: str) -> str:
    """Pick an appropriate light block based on the shell material."""
    # Nether/soul blocks get cold lights
    if any(s in shell_block for s in ("nether", "soul", "blackstone", "basalt", "crimson", "warped")):
        return random.choice(_COLD_LIGHTS)
    # Prismarine / ocean blocks get sea lanterns
    if "prismarine" in shell_block:
        return "minecraft:sea_lantern"
    # End blocks get end rods
    if any(s in shell_block for s in ("end_stone", "purpur")):
        return "minecraft:end_rod"
    return random.choice(_WARM_LIGHTS)


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
        y2 = room.origin_y + room.height - 1
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

            self._cmd(f"/setblock {x} {y} {z} minecraft:chest replace")

            if items:
                nbt = _chest_nbt(items)
                self._cmd(f"/data merge block {x} {y} {z} {nbt}")

    # ======================================================================
    # ARCHITECTURAL STYLE SYSTEM
    # ======================================================================

    def _pick_style(self, room: PlacedRoom, shape: str) -> str:
        """Pick an architectural style compatible with the room's shape and dimensions."""
        w, h, d = room.width, room.height, room.depth
        area = w * d

        # Get compatible styles for this shape
        compatible = list(_SHAPE_STYLE_COMPAT.get(shape, ["grand_hall"]))

        # Filter by dimension requirements
        candidates = []
        for style in compatible:
            if style == "cathedral" and (area < 150 or h < 7):
                continue
            if style == "grand_hall" and area < 80:
                continue
            if style == "arena" and (area < 100 or w < 10 or d < 10):
                continue
            if style == "fortress" and area < 80:
                continue
            candidates.append(style)

        # Small rooms default to catacomb or ruins
        if not candidates:
            if area < 80:
                candidates = ["catacomb", "ruins"]
            else:
                candidates = ["grand_hall"]

        return random.choice(candidates)

    def _apply_style(self, room: PlacedRoom, style: str) -> None:
        """Apply an architectural style to a room."""
        logger.info("Applying '%s' style to room '%s'", style, room.name)
        dispatch = {
            "grand_hall": self._style_grand_hall,
            "arena": self._style_arena,
            "catacomb": self._style_catacomb,
            "cathedral": self._style_cathedral,
            "fortress": self._style_fortress,
            "ruins": self._style_ruins,
        }
        handler = dispatch.get(style)
        if handler:
            handler(room)

    # -- individual style implementations ------------------------------------

    def _style_grand_hall(self, room: PlacedRoom) -> None:
        """Grand Hall: symmetrical pillars, floor border, ceiling trim, chandelier."""
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

        # Ceiling trim with contrasting material
        if h >= 5:
            trim_y = oy + h - 2
            for x in range(ox + 1, ox + w - 1):
                self._cmd(f"/setblock {x} {trim_y} {oz + 1} {pb} replace")
                self._cmd(f"/setblock {x} {trim_y} {oz + d - 2} {pb} replace")

        # Central chandelier (chain + lantern cluster) for tall rooms
        if h >= 7 and w >= 10 and d >= 10:
            mid_x = ox + w // 2
            mid_z = oz + d // 2
            light = _pick_light_block(room.shell_block)
            for dy in range(h - 2, max(h - 4, 2), -1):
                self._cmd(f"/setblock {mid_x} {oy + dy} {mid_z} minecraft:chain replace")
            self._cmd(f"/setblock {mid_x} {oy + max(h - 4, 3)} {mid_z} {light} replace")
            # Side lights
            for dx, dz in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                self._cmd(f"/setblock {mid_x + dx} {oy + max(h - 4, 3)} {mid_z + dz} {light} replace")

    def _style_arena(self, room: PlacedRoom) -> None:
        """Arena: sunken center pit, raised perimeter, optional lava/water moat, corner posts."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Raised 1-block perimeter walkway
        for x in range(ox + 1, ox + w - 1):
            for z in [oz + 1, oz + 2, oz + d - 2, oz + d - 3]:
                self._cmd(f"/setblock {x} {oy + 1} {z} {room.floor_block} replace")
        for z in range(oz + 1, oz + d - 1):
            for x in [ox + 1, ox + 2, ox + w - 2, ox + w - 3]:
                self._cmd(f"/setblock {x} {oy + 1} {z} {room.floor_block} replace")

        # Inner moat ring
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
            # Top the corner posts with lights
            if h >= 5:
                light = _pick_light_block(room.shell_block)
                self._cmd(f"/setblock {cx} {oy + min(4, h - 2)} {cz} {light} replace")

        # Center platform for large arenas
        if w >= 14 and d >= 14:
            for x in range(ox + w // 2 - 1, ox + w // 2 + 2):
                for z in range(oz + d // 2 - 1, oz + d // 2 + 2):
                    self._cmd(f"/setblock {x} {oy + 1} {z} {room.shell_block} replace")

    def _style_catacomb(self, room: PlacedRoom) -> None:
        """Catacomb: alcoves carved into walls, low arch, scattered bones, skull niches."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Wall alcoves (niches every 3 blocks along Z walls)
        if w >= 7:
            for dz in range(2, d - 2, 3):
                # Left wall alcove
                self._cmd(f"/setblock {ox} {oy + 1} {oz + dz} minecraft:air replace")
                self._cmd(f"/setblock {ox} {oy + 2} {oz + dz} minecraft:air replace")
                # Place a skull in the alcove
                if random.random() < 0.5:
                    self._cmd(f"/setblock {ox} {oy + 1} {oz + dz} minecraft:skeleton_skull replace")

                # Right wall alcove
                self._cmd(f"/setblock {ox + w - 1} {oy + 1} {oz + dz} minecraft:air replace")
                self._cmd(f"/setblock {ox + w - 1} {oy + 2} {oz + dz} minecraft:air replace")
                if random.random() < 0.5:
                    self._cmd(f"/setblock {ox + w - 1} {oy + 1} {oz + dz} minecraft:skeleton_skull replace")

        # Low arch ceiling — fill top row leaving center open
        if h >= 5:
            arch_y = oy + h - 2
            for x in [ox + 1, ox + w - 2]:
                for z in range(oz + 1, oz + d - 1):
                    self._cmd(f"/setblock {x} {arch_y} {z} {room.shell_block} replace")

        # Scattered floor bones and cobwebs
        bone_blocks = ["minecraft:bone_block", "minecraft:cobweb"]
        for _ in range(min(5, (w * d) // 20)):
            bx = random.randint(ox + 2, max(ox + 2, ox + w - 3))
            bz = random.randint(oz + 2, max(oz + 2, oz + d - 3))
            self._cmd(f"/setblock {bx} {oy + 1} {bz} {random.choice(bone_blocks)} replace")

        # Soul lighting for atmosphere
        for dz in range(3, d - 2, 5):
            self._cmd(f"/setblock {ox + 1} {oy + 1} {oz + dz} minecraft:soul_lantern replace")
            if w >= 8:
                self._cmd(f"/setblock {ox + w - 2} {oy + 1} {oz + dz} minecraft:soul_lantern replace")

    def _style_cathedral(self, room: PlacedRoom) -> None:
        """Cathedral: stepped/vaulted ceiling, tall columns, stained glass, central aisle."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Stepped ceiling — each ring inward goes 1 block higher (vaulted effect)
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

        # Stained glass windows in walls
        glass_colors = [
            "minecraft:red_stained_glass", "minecraft:blue_stained_glass",
            "minecraft:purple_stained_glass", "minecraft:yellow_stained_glass",
            "minecraft:cyan_stained_glass", "minecraft:orange_stained_glass",
        ]
        if h >= 6:
            for dz in range(3, d - 2, 4):
                glass = random.choice(glass_colors)
                for dy in range(3, min(h - 2, 6)):
                    self._cmd(f"/setblock {ox} {oy + dy} {oz + dz} {glass} replace")
                    self._cmd(f"/setblock {ox + w - 1} {oy + dy} {oz + dz} {glass} replace")

        # Central carpet/aisle (red wool down the center)
        if w >= 8:
            mid_x = ox + w // 2
            for z in range(oz + 2, oz + d - 2):
                self._cmd(f"/setblock {mid_x} {oy} {z} minecraft:red_wool replace")
                if w >= 10:
                    self._cmd(f"/setblock {mid_x - 1} {oy} {z} minecraft:red_wool replace")
                    self._cmd(f"/setblock {mid_x + 1} {oy} {z} minecraft:red_wool replace")

        # Candle clusters at the base of columns
        if d >= 10:
            for dz in range(2, d - 2, 5):
                self._cmd(f"/setblock {ox + 2} {oy + 1} {oz + dz + 1} minecraft:candle replace")
                self._cmd(f"/setblock {ox + w - 3} {oy + 1} {oz + dz + 1} minecraft:candle replace")

    def _style_fortress(self, room: PlacedRoom) -> None:
        """Fortress: thick buttresses, arrow slits, exterior battlements, weapon racks."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        pb = room.shell_block

        # Buttresses — thick supports along walls every 4 blocks
        for dz in range(1, d - 1, 4):
            for dy in range(1, h - 1):
                self._cmd(f"/setblock {ox + 1} {oy + dy} {oz + dz} {pb} replace")
            for dy in range(1, h - 1):
                self._cmd(f"/setblock {ox + w - 2} {oy + dy} {oz + dz} {pb} replace")

        # Arrow slits (iron bars in walls between buttresses)
        if h >= 5:
            for dz in range(3, d - 2, 4):
                for dy in range(2, min(h - 2, 5)):
                    self._cmd(f"/setblock {ox} {oy + dy} {oz + dz} minecraft:iron_bars replace")
                    self._cmd(f"/setblock {ox + w - 1} {oy + dy} {oz + dz} minecraft:iron_bars replace")

        # Battlements on top
        top_y = oy + h - 1
        for x in range(ox, ox + w, 2):
            self._cmd(f"/setblock {x} {top_y + 1} {oz} {pb} replace")
            self._cmd(f"/setblock {x} {top_y + 1} {oz + d - 1} {pb} replace")

        # Weapon rack simulation (armor stands or iron blocks near walls)
        if w >= 10 and d >= 10:
            rack_positions = [
                (ox + 2, oy + 1, oz + d // 2),
                (ox + w - 3, oy + 1, oz + d // 2),
            ]
            for rx, ry, rz in rack_positions:
                self._cmd(f"/setblock {rx} {ry} {rz} minecraft:smithing_table replace")
                self._cmd(f"/setblock {rx} {ry + 1} {rz} minecraft:lantern replace")

        # Interior torch sconces between buttresses
        for dz in range(3, d - 2, 4):
            self._cmd(f"/setblock {ox + 1} {oy + 2} {oz + dz} minecraft:torch replace")
            self._cmd(f"/setblock {ox + w - 2} {oy + 2} {oz + dz} minecraft:torch replace")

    def _style_ruins(self, room: PlacedRoom) -> None:
        """Ruins: partially destroyed walls, overgrown vegetation, crumbled ceiling."""
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
            bx = random.randint(ox + 1, max(ox + 1, ox + w - 2))
            bz = random.randint(oz + 1, max(oz + 1, oz + d - 2))
            self._cmd(f"/setblock {bx} {oy + 1} {bz} {random.choice(veg_blocks)} replace")

        # Overgrown walls — moss on lower sections
        for _ in range(min(6, (w + d) // 4)):
            side = random.choice(["x_min", "x_max", "z_min", "z_max"])
            if side == "x_min":
                dz = random.randint(1, d - 2)
                self._cmd(f"/setblock {ox} {oy + 1} {oz + dz} minecraft:moss_block replace")
            elif side == "x_max":
                dz = random.randint(1, d - 2)
                self._cmd(f"/setblock {ox + w - 1} {oy + 1} {oz + dz} minecraft:moss_block replace")
            elif side == "z_min":
                dx = random.randint(1, w - 2)
                self._cmd(f"/setblock {ox + dx} {oy + 1} {oz} minecraft:moss_block replace")
            else:
                dx = random.randint(1, w - 2)
                self._cmd(f"/setblock {ox + dx} {oy + 1} {oz + d - 1} minecraft:moss_block replace")

        # Crumbled ceiling patches with floor debris
        for _ in range(min(4, (w * d) // 30)):
            cx = random.randint(ox + 2, max(ox + 2, ox + w - 3))
            cz = random.randint(oz + 2, max(oz + 2, oz + d - 3))
            self._cmd(f"/setblock {cx} {oy + h - 1} {cz} minecraft:air replace")
            self._cmd(f"/setblock {cx} {oy + 1} {cz} minecraft:cobblestone replace")

        # Cracked/mossy variant of shell block on remaining walls
        mossy_map = {
            "minecraft:stone_bricks": "minecraft:mossy_stone_bricks",
            "minecraft:cobblestone": "minecraft:mossy_cobblestone",
            "minecraft:deepslate_bricks": "minecraft:cracked_deepslate_bricks",
            "minecraft:deepslate_tiles": "minecraft:cracked_deepslate_bricks",
            "minecraft:nether_bricks": "minecraft:cracked_stone_bricks",
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

    # ======================================================================
    # ROOM LIGHTING SYSTEM
    # ======================================================================

    def _light_room(self, room: PlacedRoom) -> None:
        """Add ambient lighting so rooms aren't pitch black.

        Places wall-mounted lights and ceiling-hung lanterns at regular intervals.
        The light type is chosen based on the room's shell block material.
        """
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        light = _pick_light_block(room.shell_block)

        # Wall lights at regular intervals (every 4-5 blocks along Z walls)
        if h >= 4:
            light_y = oy + min(3, h - 2)
            for dz in range(2, d - 1, 5):
                self._cmd(f"/setblock {ox + 1} {light_y} {oz + dz} {light} replace")
                if w >= 6:
                    self._cmd(f"/setblock {ox + w - 2} {light_y} {oz + dz} {light} replace")

        # Ceiling lanterns for large rooms (chain + lantern)
        if h >= 6 and w >= 10 and d >= 10:
            for dz in range(4, d - 3, 6):
                mid_x = ox + w // 2
                self._cmd(f"/setblock {mid_x} {oy + h - 2} {oz + dz} minecraft:chain replace")
                self._cmd(f"/setblock {mid_x} {oy + h - 3} {oz + dz} {light} replace")

        # Corner floor lights for atmosphere
        corners = [
            (ox + 1, oy + 1, oz + 1),
            (ox + w - 2, oy + 1, oz + 1),
            (ox + 1, oy + 1, oz + d - 2),
            (ox + w - 2, oy + 1, oz + d - 2),
        ]
        for cx, cy, cz in corners:
            if random.random() < 0.6:
                floor_light = random.choice(["minecraft:campfire", "minecraft:soul_campfire", light])
                self._cmd(f"/setblock {cx} {cy} {cz} {floor_light} replace")

    # ======================================================================
    # FLOOR PATTERN SYSTEM
    # ======================================================================

    def _apply_floor_pattern(self, room: PlacedRoom) -> None:
        """Apply a decorative floor pattern to the room."""
        pattern = random.choice(_FLOOR_PATTERNS)
        if pattern == "plain":
            return
        logger.info("Applying '%s' floor pattern to room '%s'", pattern, room.name)

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, d = room.width, room.depth
        fb = room.floor_block
        sb = room.shell_block

        if pattern == "border":
            self._floor_border(ox, oy, oz, w, d, sb)
        elif pattern == "checkered":
            self._floor_checkered(ox, oy, oz, w, d, fb, sb)
        elif pattern == "center_medallion":
            self._floor_center_medallion(ox, oy, oz, w, d, sb)
        elif pattern == "cross_path":
            self._floor_cross_path(ox, oy, oz, w, d, sb)

    def _floor_border(self, ox: int, oy: int, oz: int, w: int, d: int, block: str) -> None:
        """Place a contrasting border around the floor perimeter."""
        for x in range(ox + 1, ox + w - 1):
            self._cmd(f"/setblock {x} {oy} {oz + 1} {block} replace")
            self._cmd(f"/setblock {x} {oy} {oz + d - 2} {block} replace")
        for z in range(oz + 1, oz + d - 1):
            self._cmd(f"/setblock {ox + 1} {oy} {z} {block} replace")
            self._cmd(f"/setblock {ox + w - 2} {oy} {z} {block} replace")

    def _floor_checkered(self, ox: int, oy: int, oz: int, w: int, d: int,
                         block_a: str, block_b: str) -> None:
        """Place an alternating checkered floor pattern."""
        for x in range(ox + 1, ox + w - 1):
            for z in range(oz + 1, oz + d - 1):
                block = block_a if (x + z) % 2 == 0 else block_b
                self._cmd(f"/setblock {x} {oy} {z} {block} replace")

    def _floor_center_medallion(self, ox: int, oy: int, oz: int, w: int, d: int,
                                 block: str) -> None:
        """Place a diamond/circle pattern in the center of the floor."""
        mid_x = ox + w // 2
        mid_z = oz + d // 2
        radius = min(w, d) // 4

        for x in range(mid_x - radius, mid_x + radius + 1):
            for z in range(mid_z - radius, mid_z + radius + 1):
                if abs(x - mid_x) + abs(z - mid_z) <= radius:
                    self._cmd(f"/setblock {x} {oy} {z} {block} replace")

    def _floor_cross_path(self, ox: int, oy: int, oz: int, w: int, d: int,
                          block: str) -> None:
        """Place a cross-shaped path through the center of the floor."""
        mid_x = ox + w // 2
        mid_z = oz + d // 2

        # Vertical path (Z axis)
        for z in range(oz + 1, oz + d - 1):
            self._cmd(f"/setblock {mid_x} {oy} {z} {block} replace")
            if w >= 8:
                self._cmd(f"/setblock {mid_x - 1} {oy} {z} {block} replace")
                self._cmd(f"/setblock {mid_x + 1} {oy} {z} {block} replace")

        # Horizontal path (X axis)
        for x in range(ox + 1, ox + w - 1):
            self._cmd(f"/setblock {x} {oy} {mid_z} {block} replace")
            if d >= 8:
                self._cmd(f"/setblock {x} {oy} {mid_z - 1} {block} replace")
                self._cmd(f"/setblock {x} {oy} {mid_z + 1} {block} replace")

    # ======================================================================
    # THEMED ROOM DECORATION
    # ======================================================================

    def _apply_themed_decoration(self, room: PlacedRoom) -> None:
        """Add themed blocks based on keywords in the room's AI-given name."""
        theme = _detect_room_theme(room.name)
        if not theme:
            return

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        blocks = _ROOM_THEME_KEYWORDS[theme]

        logger.info("Applying '%s' themed decoration to room '%s'", theme, room.name)

        # Place 4-8 themed blocks in the interior
        num_placements = random.randint(4, min(8, (w - 2) * (d - 2) // 4))
        for _ in range(num_placements):
            block = random.choice(blocks)
            bx = random.randint(ox + 2, max(ox + 2, ox + w - 3))
            by = oy + 1
            bz = random.randint(oz + 2, max(oz + 2, oz + d - 3))

            # Some blocks are better on walls or ceiling
            if block in ("minecraft:cobweb", "minecraft:vine"):
                by = random.randint(oy + 2, max(oy + 2, oy + h - 2))
            elif block in ("minecraft:chain",):
                by = oy + h - 2
            elif block in ("minecraft:lantern", "minecraft:soul_lantern",
                          "minecraft:end_rod", "minecraft:sea_lantern",
                          "minecraft:redstone_lamp"):
                by = random.choice([oy + 1, oy + h - 2])

            self._cmd(f"/setblock {bx} {by} {bz} {block} replace")

    # ======================================================================
    # ENTRANCE / DOORWAY SYSTEM
    # ======================================================================

    def _enhance_room_entrance(self, room: PlacedRoom) -> None:
        """Carve an arched entrance in the +Z wall with decorative framing."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        mid_x = ox + w // 2
        entrance_z = oz + d - 1

        # Carve a 3-wide, up-to-4-tall opening
        for dx in range(-1, 2):
            for dy in range(1, min(h - 1, 4)):
                self._cmd(f"/setblock {mid_x + dx} {oy + dy} {entrance_z} minecraft:air replace")

        # Decorative arch above entrance
        if h >= 5:
            arch_y = oy + min(h - 1, 4)
            self._cmd(f"/setblock {mid_x - 1} {arch_y} {entrance_z} {room.shell_block} replace")
            self._cmd(f"/setblock {mid_x + 1} {arch_y} {entrance_z} {room.shell_block} replace")
            # Keystone
            self._cmd(f"/setblock {mid_x} {arch_y} {entrance_z} {room.ceiling_block} replace")

        # Side pillars flanking the entrance
        if h >= 6 and w >= 8:
            for dy in range(1, min(h - 1, 5)):
                self._cmd(f"/setblock {mid_x - 2} {oy + dy} {entrance_z} {room.shell_block} replace")
                self._cmd(f"/setblock {mid_x + 2} {oy + dy} {entrance_z} {room.shell_block} replace")

    def _enhance_room_back_entrance(self, room: PlacedRoom) -> None:
        """Carve an entrance in the -Z wall with decorative framing."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h = room.width, room.height

        mid_x = ox + w // 2
        entrance_z = oz

        for dx in range(-1, 2):
            for dy in range(1, min(h - 1, 4)):
                self._cmd(f"/setblock {mid_x + dx} {oy + dy} {entrance_z} minecraft:air replace")

        if h >= 5:
            arch_y = oy + min(h - 1, 4)
            self._cmd(f"/setblock {mid_x - 1} {arch_y} {entrance_z} {room.shell_block} replace")
            self._cmd(f"/setblock {mid_x + 1} {arch_y} {entrance_z} {room.shell_block} replace")
            self._cmd(f"/setblock {mid_x} {arch_y} {entrance_z} {room.ceiling_block} replace")

        if h >= 6 and w >= 8:
            for dy in range(1, min(h - 1, 5)):
                self._cmd(f"/setblock {mid_x - 2} {oy + dy} {entrance_z} {room.shell_block} replace")
                self._cmd(f"/setblock {mid_x + 2} {oy + dy} {entrance_z} {room.shell_block} replace")

    # ======================================================================
    # SHAPE VARIATIONS
    # ======================================================================

    def _pick_shape(self, room: PlacedRoom) -> str:
        """Pick a shape variation based on room dimensions."""
        w, d = room.width, room.depth
        candidates = ["rectangle", "rectangle"]  # Weight toward rectangle

        if w >= 10 and d >= 10:
            candidates.append("L-shape")
        if w >= 12 and d >= 10:
            candidates.append("T-shape")
        if w >= 8 and d >= 8:
            candidates.extend(["circle", "octagon"])
        if w >= 12 and d >= 12:
            candidates.append("cross")

        return random.choice(candidates)

    def _apply_shape(self, room: PlacedRoom, shape: str) -> None:
        """Apply a shape variation to the room."""
        if shape == "rectangle":
            return
        logger.info("Applying '%s' shape to room '%s'", shape, room.name)

        dispatch = {
            "L-shape": self._shape_L,
            "T-shape": self._shape_T,
            "circle": self._shape_circle,
            "cross": self._shape_cross,
            "octagon": self._shape_octagon,
        }
        handler = dispatch.get(shape)
        if handler:
            handler(room)

    def _shape_L(self, room: PlacedRoom) -> None:
        """Carve out a corner to make the room L-shaped.

        Only cuts the +Z corners to preserve -Z and +Z mid-wall entrances.
        """
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Cut one of the -Z corners (far from the +Z exit which is at mid-x)
        cut_w = w // 3
        cut_d = d // 3

        left_corner = random.choice([True, False])
        if left_corner:
            cx1, cx2 = ox, ox + cut_w - 1
        else:
            cx1, cx2 = ox + w - cut_w, ox + w - 1

        cz1, cz2 = oz, oz + cut_d - 1

        # Erase that corner
        for cmd in _chunked_fills(cx1, oy, cz1, cx2, oy + h - 1, cz2, "minecraft:air"):
            self._cmd(cmd)

        # Build inner walls to seal the cut
        if left_corner:
            # Vertical wall along the right side of the cut
            for cmd in _chunked_fills(cx2 + 1, oy, cz1, cx2 + 1, oy + h - 1, cz2, room.shell_block):
                self._cmd(cmd)
            # Horizontal wall along the top of the cut
            for cmd in _chunked_fills(cx1, oy, cz2 + 1, cx2, oy + h - 1, cz2 + 1, room.shell_block):
                self._cmd(cmd)
        else:
            for cmd in _chunked_fills(cx1 - 1, oy, cz1, cx1 - 1, oy + h - 1, cz2, room.shell_block):
                self._cmd(cmd)
            for cmd in _chunked_fills(cx1, oy, cz2 + 1, cx2, oy + h - 1, cz2 + 1, room.shell_block):
                self._cmd(cmd)

        # Re-carve interior of the sealed area to avoid double-thick walls
        inner_y1 = oy + 1
        inner_y2 = oy + h - 2
        if left_corner:
            # Carve interior of the remaining L
            ix1, ix2 = cx2 + 2, ox + w - 2
            iz1, iz2 = oz + 1, oz + cut_d - 1
            if ix1 <= ix2 and iz1 <= iz2 and inner_y1 <= inner_y2:
                for cmd in _chunked_fills(ix1, inner_y1, iz1, ix2, inner_y2, iz2, "minecraft:air"):
                    self._cmd(cmd)
        else:
            ix1, ix2 = ox + 1, cx1 - 2
            iz1, iz2 = oz + 1, oz + cut_d - 1
            if ix1 <= ix2 and iz1 <= iz2 and inner_y1 <= inner_y2:
                for cmd in _chunked_fills(ix1, inner_y1, iz1, ix2, inner_y2, iz2, "minecraft:air"):
                    self._cmd(cmd)

    def _shape_T(self, room: PlacedRoom) -> None:
        """Carve out two -Z corners to make the room T-shaped."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        shaft_w = max(5, w // 3)
        cut_w = (w - shaft_w) // 2
        cut_d = d // 3

        if cut_w < 2 or cut_d < 2:
            return

        # Left cut at -Z
        for cmd in _chunked_fills(ox, oy, oz, ox + cut_w - 1, oy + h - 1, oz + cut_d - 1, "minecraft:air"):
            self._cmd(cmd)
        # Seal left cut
        for cmd in _chunked_fills(ox + cut_w, oy, oz, ox + cut_w, oy + h - 1, oz + cut_d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox, oy, oz + cut_d, ox + cut_w - 1, oy + h - 1, oz + cut_d, room.shell_block):
            self._cmd(cmd)

        # Right cut at -Z
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz, ox + w - 1, oy + h - 1, oz + cut_d - 1, "minecraft:air"):
            self._cmd(cmd)
        # Seal right cut
        for cmd in _chunked_fills(ox + w - cut_w - 1, oy, oz, ox + w - cut_w - 1, oy + h - 1, oz + cut_d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz + cut_d, ox + w - 1, oy + h - 1, oz + cut_d, room.shell_block):
            self._cmd(cmd)

    def _shape_circle(self, room: PlacedRoom) -> None:
        """Carve the rectangular room into a cylinder using batched fill commands."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        cx = ox + w / 2.0
        cz = oz + d / 2.0
        radius = min(w, d) / 2.0

        # Batch: collect columns to clear and columns to set as walls
        for x in range(ox, ox + w):
            for z in range(oz, oz + d):
                dist = math.hypot(x + 0.5 - cx, z + 0.5 - cz)

                if dist > radius:
                    # Outside the circle — clear the entire column at once
                    for cmd in _chunked_fills(x, oy, z, x, oy + h - 1, z, "minecraft:air"):
                        self._cmd(cmd)
                elif dist > radius - 1.5:
                    # Just inside — this is the curved wall
                    for cmd in _chunked_fills(x, oy, z, x, oy + h - 1, z, room.shell_block):
                        self._cmd(cmd)

    def _shape_cross(self, room: PlacedRoom) -> None:
        """Carve out all four corners to make the room plus/cross-shaped."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        cut_w = w // 4
        cut_d = d // 4

        if cut_w < 2 or cut_d < 2:
            return

        # Four corners to cut
        corners = [
            (ox, oz, ox + cut_w - 1, oz + cut_d - 1),                           # -X, -Z
            (ox + w - cut_w, oz, ox + w - 1, oz + cut_d - 1),                   # +X, -Z
            (ox, oz + d - cut_d, ox + cut_w - 1, oz + d - 1),                   # -X, +Z
            (ox + w - cut_w, oz + d - cut_d, ox + w - 1, oz + d - 1),           # +X, +Z
        ]

        for cx1, cz1, cx2, cz2 in corners:
            # Clear the corner
            for cmd in _chunked_fills(cx1, oy, cz1, cx2, oy + h - 1, cz2, "minecraft:air"):
                self._cmd(cmd)

        # Seal the inner edges of each cut
        # -X, -Z corner: right edge and top edge
        for cmd in _chunked_fills(ox + cut_w, oy, oz, ox + cut_w, oy + h - 1, oz + cut_d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox, oy, oz + cut_d, ox + cut_w - 1, oy + h - 1, oz + cut_d, room.shell_block):
            self._cmd(cmd)

        # +X, -Z corner
        for cmd in _chunked_fills(ox + w - cut_w - 1, oy, oz, ox + w - cut_w - 1, oy + h - 1, oz + cut_d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz + cut_d, ox + w - 1, oy + h - 1, oz + cut_d, room.shell_block):
            self._cmd(cmd)

        # -X, +Z corner
        for cmd in _chunked_fills(ox + cut_w, oy, oz + d - cut_d, ox + cut_w, oy + h - 1, oz + d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox, oy, oz + d - cut_d - 1, ox + cut_w - 1, oy + h - 1, oz + d - cut_d - 1, room.shell_block):
            self._cmd(cmd)

        # +X, +Z corner
        for cmd in _chunked_fills(ox + w - cut_w - 1, oy, oz + d - cut_d, ox + w - cut_w - 1, oy + h - 1, oz + d - 1, room.shell_block):
            self._cmd(cmd)
        for cmd in _chunked_fills(ox + w - cut_w, oy, oz + d - cut_d - 1, ox + w - 1, oy + h - 1, oz + d - cut_d - 1, room.shell_block):
            self._cmd(cmd)

    def _shape_octagon(self, room: PlacedRoom) -> None:
        """Carve the corners to approximate an octagonal room."""
        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Cut size is proportional to the room dimensions
        cut = min(w, d) // 4
        if cut < 2:
            return

        # Four triangle-ish corners
        for cx in range(cut):
            remaining = cut - cx - 1
            if remaining <= 0:
                continue
            # -X, -Z corner
            for cmd in _chunked_fills(ox + cx, oy, oz, ox + cx, oy + h - 1, oz + remaining - 1, room.shell_block):
                self._cmd(cmd)
            # +X, -Z corner
            for cmd in _chunked_fills(ox + w - 1 - cx, oy, oz, ox + w - 1 - cx, oy + h - 1, oz + remaining - 1, room.shell_block):
                self._cmd(cmd)
            # -X, +Z corner
            for cmd in _chunked_fills(ox + cx, oy, oz + d - remaining, ox + cx, oy + h - 1, oz + d - 1, room.shell_block):
                self._cmd(cmd)
            # +X, +Z corner
            for cmd in _chunked_fills(ox + w - 1 - cx, oy, oz + d - remaining, ox + w - 1 - cx, oy + h - 1, oz + d - 1, room.shell_block):
                self._cmd(cmd)

    # ======================================================================
    # CORRIDOR ENHANCEMENTS
    # ======================================================================

    def _enhance_corridor_lighting(self, corridor: PlacedCorridor) -> None:
        """Place lanterns along the corridor ceiling at intervals."""
        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, h, length = corridor.width, corridor.height, corridor.length

        mid_x = ox + w // 2
        light_y = oy + h - 2

        light = _pick_light_block(corridor.block)

        for dz in range(2, length - 1, 3):
            self._cmd(f"/setblock {mid_x} {light_y} {oz + dz} minecraft:chain replace")
            if light_y - 1 > oy:
                self._cmd(f"/setblock {mid_x} {light_y - 1} {oz + dz} {light} replace")

    def _enhance_corridor_floor(self, corridor: PlacedCorridor) -> None:
        """Add a contrasting floor strip down the center of corridors."""
        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, length = corridor.width, corridor.length

        mid_x = ox + w // 2
        for dz in range(1, length - 1):
            self._cmd(f"/setblock {mid_x} {oy} {oz + dz} {corridor.block} replace")

    def _apply_corridor_style(self, corridor: PlacedCorridor) -> None:
        """Apply a random decorative style to a corridor."""
        style = random.choice(_CORRIDOR_STYLES)
        if style == "plain":
            return

        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, h, length = corridor.width, corridor.height, corridor.length

        if style == "arched":
            # Arched ceiling — place blocks along the top edges
            if w >= 3 and h >= 4:
                for dz in range(1, length - 1):
                    self._cmd(f"/setblock {ox + 1} {oy + h - 2} {oz + dz} {corridor.block} replace")
                    if w >= 4:
                        self._cmd(f"/setblock {ox + w - 2} {oy + h - 2} {oz + dz} {corridor.block} replace")

        elif style == "pillared":
            # Small pillar pairs at intervals
            if w >= 4:
                for dz in range(2, length - 1, 4):
                    for dy in range(1, h - 1):
                        self._cmd(f"/setblock {ox + 1} {oy + dy} {oz + dz} {corridor.block} replace")
                        self._cmd(f"/setblock {ox + w - 2} {oy + dy} {oz + dz} {corridor.block} replace")

        elif style == "trapped":
            # Tripwire hooks and pressure plates
            for dz in range(3, length - 2, 5):
                self._cmd(f"/setblock {ox + w // 2} {oy} {oz + dz} minecraft:stone_pressure_plate replace")
            # Cobwebs and dispensers
            for dz in range(4, length - 2, 6):
                if h >= 4:
                    self._cmd(f"/setblock {ox + 1} {oy + h - 2} {oz + dz} minecraft:cobweb replace")

        elif style == "ornate":
            # Decorative floor patterns and wall detail
            for dz in range(1, length - 1, 2):
                self._cmd(f"/setblock {ox + w // 2} {oy} {oz + dz} minecraft:chiseled_stone_bricks replace")

    def _build_corridor_bend(self, corridor: PlacedCorridor) -> None:
        """Build the L-shaped bend segment for corridors connecting offset rooms."""
        if not corridor.has_bend:
            return

        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, h = corridor.width, corridor.height

        # Build the horizontal (X-direction) segment at the bend point
        bend_z = corridor.bend_z
        bend_dir = corridor.bend_dir
        bend_len = corridor.bend_length

        if bend_dir > 0:
            # Bend extends in +X
            bx1 = ox + w - 1
            bx2 = bx1 + bend_len
        else:
            # Bend extends in -X
            bx2 = ox
            bx1 = bx2 - bend_len

        # Ensure proper min/max ordering
        bx_min = min(bx1, bx2)
        bx_max = max(bx1, bx2)

        # Build the bend shell
        for cmd in _chunked_fills(bx_min, oy, bend_z - 1, bx_max, oy + h - 1, bend_z + 1, corridor.block):
            self._cmd(cmd)

        # Carve the bend interior
        if bx_min + 1 <= bx_max - 1:
            for cmd in _chunked_fills(bx_min + 1, oy + 1, bend_z, bx_max - 1, oy + h - 2, bend_z, "minecraft:air"):
                self._cmd(cmd)

        # Open the connection points
        for cmd in _chunked_fills(bx_min, oy + 1, bend_z, bx_min, oy + h - 2, bend_z, "minecraft:air"):
            self._cmd(cmd)
        for cmd in _chunked_fills(bx_max, oy + 1, bend_z, bx_max, oy + h - 2, bend_z, "minecraft:air"):
            self._cmd(cmd)

        # Lighting in the bend
        light = _pick_light_block(corridor.block)
        mid_bx = (bx_min + bx_max) // 2
        if h >= 3:
            self._cmd(f"/setblock {mid_bx} {oy + h - 2} {bend_z} {light} replace")

    def _build_corridor_staircase(self, corridor: PlacedCorridor) -> None:
        """Build staircase blocks for corridors with Y-offset between rooms."""
        if corridor.y_offset == 0:
            return

        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, h, length = corridor.width, corridor.height, corridor.length

        y_diff = corridor.y_offset
        mid_x = ox + w // 2

        # Calculate stair placement: distribute steps evenly along the corridor
        steps = abs(y_diff)
        if steps == 0 or length < steps + 2:
            return

        step_interval = max(1, (length - 2) // steps)
        direction = 1 if y_diff > 0 else -1

        stair_block = "minecraft:stone_brick_stairs" if "stone" in corridor.block else "minecraft:cobblestone_stairs"

        for i in range(steps):
            step_z = oz + 1 + i * step_interval
            step_y = oy + 1 + (i * direction if direction > 0 else (steps - 1 - i))

            if step_z >= oz + length - 1:
                break

            # Place stair block at each step position
            for x in range(ox + 1, ox + w - 1):
                self._cmd(f"/setblock {x} {step_y} {step_z} {stair_block} replace")

            # Clear air above stairs for headroom
            for x in range(ox + 1, ox + w - 1):
                for dy in range(1, h - 1):
                    if step_y + dy <= oy + h - 2:
                        self._cmd(f"/setblock {x} {step_y + dy} {step_z} minecraft:air replace")

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
        """Phase (c): carve air at both Z-ends so the corridor connects to rooms."""
        ix1 = corridor.origin_x + 1
        ix2 = corridor.origin_x + corridor.width - 2
        iy1 = corridor.origin_y + 1
        iy2 = corridor.origin_y + corridor.height - 2

        if ix1 > ix2 or iy1 > iy2:
            return

        # Z-min end
        z_min = corridor.origin_z
        for cmd in _chunked_fills(ix1, iy1, z_min, ix2, iy2, z_min, "minecraft:air"):
            self._cmd(cmd)

        # Z-max end
        z_max = corridor.origin_z + corridor.length - 1
        for cmd in _chunked_fills(ix1, iy1, z_max, ix2, iy2, z_max, "minecraft:air"):
            self._cmd(cmd)

    # ======================================================================
    # BUILDING FEATURES: ROOFS, WINDOWS, DOORS, MULTI-STORY, EXTERIORS
    # ======================================================================

    def _build_roof(self, room: PlacedRoom) -> None:
        """Build a roof on top of the room based on roof_type."""
        roof_type = room.roof_type
        if roof_type == "none":
            return

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth
        top_y = oy + h  # just above the ceiling

        # Pick roof block — use ceiling_block or a contrasting material
        roof_block = room.ceiling_block
        # Wood roofs for wood buildings
        if "planks" in room.shell_block:
            wood_type = room.shell_block.replace("_planks", "")
            slab_id = f"{wood_type}_slab"
            stair_id = f"{wood_type}_stairs"
            # Check if the slab/stair exists, otherwise use generic
            from backend.registries import VALID_BLOCK_IDS
            if slab_id not in VALID_BLOCK_IDS:
                slab_id = "minecraft:oak_slab"
                stair_id = "minecraft:oak_stairs"
            roof_block = slab_id
        elif "stone" in room.shell_block or "brick" in room.shell_block:
            roof_block = "minecraft:stone_brick_slab"
        elif "deepslate" in room.shell_block:
            roof_block = "minecraft:deepslate_tile_slab"

        logger.info("Building '%s' roof on '%s'", roof_type, room.name)

        if roof_type == "peaked":
            self._roof_peaked(ox, top_y, oz, w, d, room.shell_block)
        elif roof_type == "gable":
            self._roof_gable(ox, top_y, oz, w, d, room.shell_block)
        elif roof_type == "dome":
            self._roof_dome(ox, top_y, oz, w, d, room.shell_block)
        elif roof_type == "flat":
            self._roof_flat(ox, top_y, oz, w, d, room.shell_block)

    def _roof_peaked(self, ox: int, base_y: int, oz: int, w: int, d: int, block: str) -> None:
        """Build a peaked/A-frame roof — triangle cross-section along X."""
        peak_height = max(2, w // 3)

        for layer in range(peak_height):
            # Each layer is narrower as we go up
            inset = layer + 1
            x1 = ox + inset
            x2 = ox + w - 1 - inset
            y = base_y + layer

            if x1 > x2:
                # Top ridge — single line
                x1 = x2 = ox + w // 2
                for z in range(oz, oz + d):
                    self._cmd(f"/setblock {x1} {y} {z} {block} replace")
                break

            # Left slope and right slope
            for z in range(oz, oz + d):
                self._cmd(f"/setblock {x1} {y} {z} {block} replace")
                self._cmd(f"/setblock {x2} {y} {z} {block} replace")

            # Fill the flat top of this layer
            if x1 + 1 <= x2 - 1:
                for z in [oz, oz + d - 1]:
                    for cmd in _chunked_fills(x1, y, z, x2, y, z, block):
                        self._cmd(cmd)

        # Gable ends (triangular walls on Z-min and Z-max faces)
        for layer in range(peak_height):
            inset = layer + 1
            x1 = ox + inset
            x2 = ox + w - 1 - inset
            y = base_y + layer
            if x1 > x2:
                break
            for cmd in _chunked_fills(x1, y, oz, x2, y, oz, block):
                self._cmd(cmd)
            for cmd in _chunked_fills(x1, y, oz + d - 1, x2, y, oz + d - 1, block):
                self._cmd(cmd)

    def _roof_gable(self, ox: int, base_y: int, oz: int, w: int, d: int, block: str) -> None:
        """Build a gable roof — peaked along the Z axis."""
        peak_height = max(2, d // 3)

        for layer in range(peak_height):
            inset = layer + 1
            z1 = oz + inset
            z2 = oz + d - 1 - inset
            y = base_y + layer

            if z1 > z2:
                z1 = z2 = oz + d // 2
                for x in range(ox, ox + w):
                    self._cmd(f"/setblock {x} {y} {z1} {block} replace")
                break

            for x in range(ox, ox + w):
                self._cmd(f"/setblock {x} {y} {z1} {block} replace")
                self._cmd(f"/setblock {x} {y} {z2} {block} replace")

            # Gable ends
            if z1 + 1 <= z2 - 1:
                for x in [ox, ox + w - 1]:
                    for cmd in _chunked_fills(x, y, z1, x, y, z2, block):
                        self._cmd(cmd)

    def _roof_dome(self, ox: int, base_y: int, oz: int, w: int, d: int, block: str) -> None:
        """Build a dome roof — hemispherical approximation."""
        radius_x = w / 2.0
        radius_z = d / 2.0
        radius = min(radius_x, radius_z)
        cx = ox + w / 2.0
        cz = oz + d / 2.0
        dome_height = max(2, int(radius * 0.7))

        for layer in range(dome_height):
            y = base_y + layer
            # Calculate the radius at this height
            t = (layer + 1) / dome_height
            layer_radius = radius * math.cos(t * math.pi / 2)

            for x in range(ox, ox + w):
                for z in range(oz, oz + d):
                    dist = math.hypot(x + 0.5 - cx, z + 0.5 - cz)
                    if dist <= layer_radius and dist >= layer_radius - 1.5:
                        self._cmd(f"/setblock {x} {y} {z} {block} replace")
                    elif layer == dome_height - 1 and dist <= layer_radius:
                        # Cap the top
                        self._cmd(f"/setblock {x} {y} {z} {block} replace")

    def _roof_flat(self, ox: int, base_y: int, oz: int, w: int, d: int, block: str) -> None:
        """Build a flat roof with raised parapet/battlements."""
        # Flat slab on top
        for cmd in _chunked_fills(ox, base_y, oz, ox + w - 1, base_y, oz + d - 1, block):
            self._cmd(cmd)

        # Parapet wall (1 block high border)
        parapet_y = base_y + 1
        for x in range(ox, ox + w):
            self._cmd(f"/setblock {x} {parapet_y} {oz} {block} replace")
            self._cmd(f"/setblock {x} {parapet_y} {oz + d - 1} {block} replace")
        for z in range(oz, oz + d):
            self._cmd(f"/setblock {ox} {parapet_y} {z} {block} replace")
            self._cmd(f"/setblock {ox + w - 1} {parapet_y} {z} {block} replace")

        # Merlons (battlements) — every other block is raised
        merlon_y = base_y + 2
        for x in range(ox, ox + w, 2):
            self._cmd(f"/setblock {x} {merlon_y} {oz} {block} replace")
            self._cmd(f"/setblock {x} {merlon_y} {oz + d - 1} {block} replace")
        for z in range(oz, oz + d, 2):
            self._cmd(f"/setblock {ox} {merlon_y} {z} {block} replace")
            self._cmd(f"/setblock {ox + w - 1} {merlon_y} {z} {block} replace")

    def _build_windows(self, room: PlacedRoom) -> None:
        """Add windows to the walls of a building."""
        if not room.has_windows:
            return

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        # Window material — glass panes for houses, iron bars for castles
        if any(s in room.shell_block for s in ("stone", "brick", "deepslate", "blackstone")):
            window_block = "minecraft:iron_bars"
        else:
            window_block = "minecraft:glass_pane"

        # Window height (start at y+2 so there's a sill)
        win_y_start = oy + 2
        win_y_end = min(oy + h - 2, win_y_start + 2)

        if win_y_start > win_y_end:
            return

        # Place windows every 4-5 blocks along each wall
        # X walls (at z=0 and z=d-1)
        for x in range(ox + 2, ox + w - 2, 4):
            for y in range(win_y_start, win_y_end + 1):
                self._cmd(f"/setblock {x} {y} {oz} {window_block} replace")
                self._cmd(f"/setblock {x} {y} {oz + d - 1} {window_block} replace")

        # Z walls (at x=0 and x=w-1)
        for z in range(oz + 2, oz + d - 2, 4):
            for y in range(win_y_start, win_y_end + 1):
                self._cmd(f"/setblock {ox} {y} {z} {window_block} replace")
                self._cmd(f"/setblock {ox + w - 1} {y} {z} {window_block} replace")

        # Multi-story: add windows on upper floors too
        if room.num_floors > 1:
            floor_height = max(4, (h - 1) // room.num_floors)
            for floor in range(1, room.num_floors):
                floor_y = oy + floor * floor_height
                wy_start = floor_y + 2
                wy_end = min(floor_y + floor_height - 1, wy_start + 2)
                if wy_start > wy_end or wy_end >= oy + h - 1:
                    continue
                for x in range(ox + 2, ox + w - 2, 4):
                    for y in range(wy_start, wy_end + 1):
                        self._cmd(f"/setblock {x} {y} {oz} {window_block} replace")
                        self._cmd(f"/setblock {x} {y} {oz + d - 1} {window_block} replace")

    def _build_door(self, room: PlacedRoom) -> None:
        """Add a door at ground level on the -Z face of the building."""
        if not room.has_door:
            return

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h = room.width, room.height

        mid_x = ox + w // 2
        door_z = oz  # Front face (-Z)

        # Carve door opening (2 tall, 1 wide)
        self._cmd(f"/setblock {mid_x} {oy + 1} {door_z} minecraft:air replace")
        self._cmd(f"/setblock {mid_x} {oy + 2} {door_z} minecraft:air replace")

        # Place door block
        door_type = "minecraft:oak_door"
        if "spruce" in room.shell_block:
            door_type = "minecraft:oak_door"  # spruce_door doesn't exist in our registry
        elif "dark_oak" in room.shell_block:
            door_type = "minecraft:oak_door"

        # Door frame — contrasting blocks around the opening
        frame_block = room.shell_block
        self._cmd(f"/setblock {mid_x - 1} {oy + 1} {door_z} {frame_block} replace")
        self._cmd(f"/setblock {mid_x - 1} {oy + 2} {door_z} {frame_block} replace")
        self._cmd(f"/setblock {mid_x + 1} {oy + 1} {door_z} {frame_block} replace")
        self._cmd(f"/setblock {mid_x + 1} {oy + 2} {door_z} {frame_block} replace")
        self._cmd(f"/setblock {mid_x} {oy + 3} {door_z} {frame_block} replace")

        # Wider entrance for larger buildings
        if w >= 12:
            self._cmd(f"/setblock {mid_x - 1} {oy + 1} {door_z} minecraft:air replace")
            self._cmd(f"/setblock {mid_x - 1} {oy + 2} {door_z} minecraft:air replace")
            self._cmd(f"/setblock {mid_x + 1} {oy + 1} {door_z} minecraft:air replace")
            self._cmd(f"/setblock {mid_x + 1} {oy + 2} {door_z} minecraft:air replace")

        # Porch light
        if h >= 5:
            light = _pick_light_block(room.shell_block)
            self._cmd(f"/setblock {mid_x} {oy + 3} {door_z} {light} replace")

    def _build_multi_story_floors(self, room: PlacedRoom) -> None:
        """Split a tall room into multiple floors with floor slabs and ladders."""
        if room.num_floors <= 1:
            return

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, h, d = room.width, room.height, room.depth

        floor_height = max(4, (h - 1) // room.num_floors)

        for floor in range(1, room.num_floors):
            floor_y = oy + floor * floor_height

            if floor_y >= oy + h - 2:
                break

            # Floor slab
            for cmd in _chunked_fills(
                ox + 1, floor_y, oz + 1,
                ox + w - 2, floor_y, oz + d - 2,
                room.floor_block,
            ):
                self._cmd(cmd)

            # Carve headroom above the floor
            if floor_y + 1 <= oy + h - 2:
                for cmd in _chunked_fills(
                    ox + 1, floor_y + 1, oz + 1,
                    ox + w - 2, min(floor_y + floor_height - 1, oy + h - 2), oz + d - 2,
                    "minecraft:air",
                ):
                    self._cmd(cmd)

            # Stairwell opening (2x2 hole in a corner)
            stair_x = ox + w - 3
            stair_z = oz + 1
            for cmd in _chunked_fills(stair_x, floor_y, stair_z, stair_x + 1, floor_y, stair_z + 1, "minecraft:air"):
                self._cmd(cmd)

        # Place ladders in the stairwell
        stair_x = ox + w - 3
        stair_z = oz + 1
        for y in range(oy + 1, oy + h - 1):
            self._cmd(f"/setblock {stair_x} {y} {stair_z} minecraft:ladder replace")

    def _build_exterior(self, room: PlacedRoom) -> None:
        """Build exterior features around a building."""
        ext = room.exterior_type
        if ext == "none":
            return

        ox, oy, oz = room.origin_x, room.origin_y, room.origin_z
        w, d = room.width, room.depth

        logger.info("Building '%s' exterior for '%s'", ext, room.name)

        if ext == "fence":
            self._exterior_fence(ox, oy, oz, w, d)
        elif ext == "garden":
            self._exterior_garden(ox, oy, oz, w, d)
        elif ext == "porch":
            self._exterior_porch(ox, oy, oz, w, d, room.shell_block)
        elif ext == "wall":
            self._exterior_wall(ox, oy, oz, w, d, room.shell_block)

    def _exterior_fence(self, ox: int, oy: int, oz: int, w: int, d: int) -> None:
        """Place a fence perimeter around the building with a gap for the door."""
        pad = 2
        fx1, fz1 = ox - pad, oz - pad
        fx2, fz2 = ox + w - 1 + pad, oz + d - 1 + pad
        mid_x = ox + w // 2

        # Fence along perimeter
        for x in range(fx1, fx2 + 1):
            self._cmd(f"/setblock {x} {oy + 1} {fz1} minecraft:oak_fence replace")
            self._cmd(f"/setblock {x} {oy + 1} {fz2} minecraft:oak_fence replace")
        for z in range(fz1, fz2 + 1):
            self._cmd(f"/setblock {fx1} {oy + 1} {z} minecraft:oak_fence replace")
            self._cmd(f"/setblock {fx2} {oy + 1} {z} minecraft:oak_fence replace")

        # Gate opening at the front (-Z)
        self._cmd(f"/setblock {mid_x} {oy + 1} {fz1} minecraft:air replace")
        self._cmd(f"/setblock {mid_x - 1} {oy + 1} {fz1} minecraft:air replace")

        # Corner fence posts
        for cx, cz in [(fx1, fz1), (fx2, fz1), (fx1, fz2), (fx2, fz2)]:
            self._cmd(f"/setblock {cx} {oy + 1} {cz} minecraft:oak_log replace")

    def _exterior_garden(self, ox: int, oy: int, oz: int, w: int, d: int) -> None:
        """Place flowers and paths around the building."""
        pad = 2
        flowers = ["minecraft:grass_block", "minecraft:moss_carpet", "minecraft:flower_pot"]

        # Surround with grass and flowers
        for x in range(ox - pad, ox + w + pad):
            for z in range(oz - pad, oz + d + pad):
                if ox <= x < ox + w and oz <= z < oz + d:
                    continue  # skip under the building
                if random.random() < 0.3:
                    self._cmd(f"/setblock {x} {oy} {z} minecraft:grass_block replace")
                    if random.random() < 0.2:
                        self._cmd(f"/setblock {x} {oy + 1} {z} {random.choice(flowers)} replace")

        # Path to front door
        mid_x = ox + w // 2
        for z in range(oz - pad, oz):
            self._cmd(f"/setblock {mid_x} {oy} {z} minecraft:gravel replace")
            self._cmd(f"/setblock {mid_x - 1} {oy} {z} minecraft:gravel replace")

    def _exterior_porch(self, ox: int, oy: int, oz: int, w: int, d: int, block: str) -> None:
        """Build a covered porch on the front (-Z) of the building."""
        porch_depth = 3
        porch_z1 = oz - porch_depth
        porch_z2 = oz - 1
        mid_x = ox + w // 2

        # Porch floor
        for cmd in _chunked_fills(ox, oy, porch_z1, ox + w - 1, oy, porch_z2, "minecraft:cobblestone"):
            self._cmd(cmd)

        # Porch pillars at corners
        for dy in range(1, 4):
            self._cmd(f"/setblock {ox} {oy + dy} {porch_z1} {block} replace")
            self._cmd(f"/setblock {ox + w - 1} {oy + dy} {porch_z1} {block} replace")

        # Porch roof
        for cmd in _chunked_fills(ox, oy + 4, porch_z1, ox + w - 1, oy + 4, porch_z2, block):
            self._cmd(cmd)

    def _exterior_wall(self, ox: int, oy: int, oz: int, w: int, d: int, block: str) -> None:
        """Build a defensive wall perimeter around the building."""
        pad = 3
        wx1, wz1 = ox - pad, oz - pad
        wx2, wz2 = ox + w - 1 + pad, oz + d - 1 + pad
        wall_height = 4
        mid_x = ox + w // 2

        # Walls
        for y in range(oy + 1, oy + 1 + wall_height):
            for x in range(wx1, wx2 + 1):
                self._cmd(f"/setblock {x} {y} {wz1} {block} replace")
                self._cmd(f"/setblock {x} {y} {wz2} {block} replace")
            for z in range(wz1, wz2 + 1):
                self._cmd(f"/setblock {wx1} {y} {z} {block} replace")
                self._cmd(f"/setblock {wx2} {y} {z} {block} replace")

        # Gate opening at -Z
        for dy in range(1, wall_height):
            self._cmd(f"/setblock {mid_x} {oy + dy} {wz1} minecraft:air replace")
            self._cmd(f"/setblock {mid_x - 1} {oy + dy} {wz1} minecraft:air replace")
            self._cmd(f"/setblock {mid_x + 1} {oy + dy} {wz1} minecraft:air replace")

        # Battlements on top
        top_y = oy + 1 + wall_height
        for x in range(wx1, wx2 + 1, 2):
            self._cmd(f"/setblock {x} {top_y} {wz1} {block} replace")
            self._cmd(f"/setblock {x} {top_y} {wz2} {block} replace")
        for z in range(wz1, wz2 + 1, 2):
            self._cmd(f"/setblock {wx1} {top_y} {z} {block} replace")
            self._cmd(f"/setblock {wx2} {top_y} {z} {block} replace")

    # ======================================================================
    # PATH BUILDING (for villages — open-air connections)
    # ======================================================================

    def _build_path(self, corridor: PlacedCorridor) -> None:
        """Build an open-air path between buildings (for villages)."""
        ox, oy, oz = corridor.origin_x, corridor.origin_y, corridor.origin_z
        w, length = corridor.width, corridor.length

        # Path surface
        path_block = corridor.block
        if path_block in ("minecraft:stone_bricks", "minecraft:cobblestone"):
            path_block = "minecraft:gravel"

        for z in range(oz, oz + length):
            for x in range(ox, ox + w):
                self._cmd(f"/setblock {x} {oy} {z} {path_block} replace")
                # Clear air above the path
                self._cmd(f"/setblock {x} {oy + 1} {z} minecraft:air replace")
                self._cmd(f"/setblock {x} {oy + 2} {z} minecraft:air replace")

        # Path edge decoration (flowers/torches)
        if w >= 3:
            for z in range(oz + 1, oz + length - 1, 4):
                light = random.choice(["minecraft:torch", "minecraft:lantern"])
                self._cmd(f"/setblock {ox - 1} {oy + 1} {z} {light} replace")
                self._cmd(f"/setblock {ox + w} {oy + 1} {z} {light} replace")

        # Handle L-shaped bends in paths
        if corridor.has_bend:
            self._build_path_bend(corridor, path_block)

    def _build_path_bend(self, corridor: PlacedCorridor, path_block: str) -> None:
        """Build the L-shaped bend segment for open-air paths."""
        ox, oy = corridor.origin_x, corridor.origin_y
        w = corridor.width
        bend_z = corridor.bend_z
        bend_dir = corridor.bend_dir
        bend_len = corridor.bend_length

        if bend_dir > 0:
            bx_start = ox + w
            bx_end = bx_start + bend_len
        else:
            bx_end = ox - 1
            bx_start = bx_end - bend_len

        bx_min = min(bx_start, bx_end)
        bx_max = max(bx_start, bx_end)

        for x in range(bx_min, bx_max + 1):
            for z in range(bend_z - 1, bend_z + 2):
                self._cmd(f"/setblock {x} {oy} {z} {path_block} replace")
                self._cmd(f"/setblock {x} {oy + 1} {z} minecraft:air replace")

    # ======================================================================
    # HIGH-LEVEL BUILD ORCHESTRATION
    # ======================================================================

    def _build_room(self, room: PlacedRoom, room_index: int = 0,
                    total_rooms: int = 1, structure_type: str = "dungeon") -> None:
        """Execute all build phases for a single room/building.

        Build order:
        1. Exterior features (fence, garden, wall — built FIRST so room overlays)
        2. Shell (solid block fill)
        3. Floor
        4. Ceiling
        5. Carve interior (hollow out)
        6. Multi-story floors
        7. Shape variation (L, T, circle, cross, octagon) — dungeon only
        8. Floor pattern
        9. Architectural style (grand_hall, arena, etc.) — dungeon only
        10. Windows
        11. Door
        12. Roof
        13. Ambient lighting
        14. Themed decoration (based on room name)
        15. Entrance/doorway carving (for dungeons with corridors)
        16. AI-generated details, mobs, loot (placed LAST to override)
        """
        is_dungeon = structure_type in ("dungeon", "mine", "prison")
        is_building = structure_type in (
            "village", "house", "castle", "tower", "tavern", "farm",
            "marketplace", "lighthouse", "mansion", "library",
        )

        # Phase 1: Exterior (before shell so building sits on top)
        if is_building:
            self._build_exterior(room)

        # Phase 2-5: Core structure
        self._build_room_shell(room)
        self._build_room_floor(room)
        self._build_room_ceiling(room)
        self._carve_room_interior(room)

        # Phase 6: Multi-story floors
        self._build_multi_story_floors(room)

        # Phase 7: Shape variation (dungeons only — buildings should be rectangular)
        shape = "rectangle"
        if is_dungeon:
            shape = self._pick_shape(room)
            self._apply_shape(room, shape)

        # Phase 8: Floor pattern
        self._apply_floor_pattern(room)

        # Phase 9: Architectural style (dungeons only)
        if is_dungeon:
            style = self._pick_style(room, shape)
            self._apply_style(room, style)

        # Phase 10-11: Windows and doors (buildings only)
        if is_building or room.has_windows:
            self._build_windows(room)
        if is_building or room.has_door:
            self._build_door(room)

        # Phase 12: Roof
        self._build_roof(room)

        # Phase 13: Ambient lighting
        self._light_room(room)

        # Phase 14: Themed decoration
        self._apply_themed_decoration(room)

        # Phase 15: Entrances (for corridored structures)
        if is_dungeon:
            if room_index < total_rooms - 1:
                self._enhance_room_entrance(room)
            if room_index > 0:
                self._enhance_room_back_entrance(room)

        # Phase 16: AI-generated content (placed LAST so it overrides everything)
        self._place_room_details(room)
        self._spawn_room_mobs(room)
        self._place_room_loot_chests(room)

    def _build_corridor(self, corridor: PlacedCorridor) -> None:
        """Execute all build phases for a single corridor or path.

        For enclosed corridors (dungeons):
        1. Shell -> Carve interior -> Open ends -> Bend -> Stairs -> Style -> Lighting

        For open-air paths (villages):
        1. Path surface -> Edge decoration -> Bend
        """
        if corridor.is_path:
            self._build_path(corridor)
            return

        self._build_corridor_shell(corridor)
        self._carve_corridor_interior(corridor)
        self._open_corridor_ends(corridor)

        # L-shaped bend for X-offset rooms
        self._build_corridor_bend(corridor)

        # Staircase for Y-offset rooms
        self._build_corridor_staircase(corridor)

        # Decorative enhancements
        self._apply_corridor_style(corridor)
        self._enhance_corridor_lighting(corridor)
        self._enhance_corridor_floor(corridor)

    # -- clear build area ----------------------------------------------------

    def _compute_bounding_box(self, placed: PlacedBlueprint) -> tuple[int, int, int, int, int, int]:
        """Compute the axis-aligned bounding box of the entire dungeon.

        Returns (x_min, y_min, z_min, x_max, y_max, z_max).
        """
        x_min = y_min = z_min = float("inf")
        x_max = y_max = z_max = float("-inf")

        for room in placed.rooms:
            x_min = min(x_min, room.origin_x)
            y_min = min(y_min, room.origin_y)
            z_min = min(z_min, room.origin_z)
            x_max = max(x_max, room.origin_x + room.width - 1)
            y_max = max(y_max, room.origin_y + room.height - 1)
            z_max = max(z_max, room.origin_z + room.depth - 1)

        for corridor in placed.corridors:
            x_min = min(x_min, corridor.origin_x)
            y_min = min(y_min, corridor.origin_y)
            z_min = min(z_min, corridor.origin_z)
            x_max = max(x_max, corridor.origin_x + corridor.width - 1)
            y_max = max(y_max, corridor.origin_y + corridor.height - 1)
            z_max = max(z_max, corridor.origin_z + corridor.length - 1)

            # Account for L-shaped bend segments
            if corridor.has_bend:
                if corridor.bend_dir > 0:
                    x_max = max(x_max, corridor.origin_x + corridor.width - 1 + corridor.bend_length)
                else:
                    x_min = min(x_min, corridor.origin_x - corridor.bend_length)

        return int(x_min), int(y_min), int(z_min), int(x_max), int(y_max), int(z_max)

    def _clear_build_area(self, placed: PlacedBlueprint, padding: int = 2) -> None:
        """Clear the entire dungeon footprint (plus padding) with air.

        This removes any terrain that would otherwise clip through the dungeon
        walls, giving it a clean build space.
        """
        x_min, y_min, z_min, x_max, y_max, z_max = self._compute_bounding_box(placed)

        # Add padding around the sides and top so the dungeon sits in open space.
        # No padding below — the floor should rest on the ground.
        x_min -= padding
        x_max += padding
        z_min -= padding
        z_max += padding
        y_max += padding

        logger.info(
            "Clearing build area: (%d,%d,%d) to (%d,%d,%d)",
            x_min, y_min, z_min, x_max, y_max, z_max,
        )

        for cmd in _chunked_fills(x_min, y_min, z_min, x_max, y_max, z_max, "minecraft:air"):
            self._cmd(cmd)

    # -- public API ----------------------------------------------------------

    async def build(self, placed: PlacedBlueprint) -> dict:
        """Build all rooms and corridors from *placed* in the Minecraft world.

        Sends coloured progress messages via ``/tellraw`` and pauses between
        rooms to avoid server lag.

        Returns a summary ``dict`` with:
        - ``name``: the structure name
        - ``room_count``: number of rooms/buildings built
        - ``structure_type``: the type of structure
        """
        total_rooms = len(placed.rooms)
        total_corridors = len(placed.corridors)
        structure_type = placed.structure_type

        # Label for user-facing messages
        is_village = structure_type in ("village", "marketplace", "farm")
        room_label = "building" if is_village else "room"
        connection_label = "path" if is_village else "corridor"

        self.connect()
        try:
            self._cmd(
                _tellraw(
                    f"[NemoCraft] Starting build: \"{placed.name}\" "
                    f"({total_rooms} {room_label}(s), {total_corridors} {connection_label}(s))",
                    color="green",
                )
            )

            # Clear the build area so terrain doesn't clip through walls.
            self._cmd(_tellraw("[NemoCraft] Clearing build area...", color="yellow"))
            self._clear_build_area(placed)
            await asyncio.sleep(settings.build_delay)

            # -- Build rooms / buildings -------------------------------------
            for idx, room in enumerate(placed.rooms, start=1):
                self._cmd(
                    _tellraw(
                        f'[NemoCraft] Building {room_label}: "{room.name}" '
                        f"({idx}/{total_rooms})...",
                        color="gold",
                    )
                )
                self._build_room(
                    room,
                    room_index=idx - 1,
                    total_rooms=total_rooms,
                    structure_type=structure_type,
                )
                logger.info("Built %s %d/%d: %s", room_label, idx, total_rooms, room.name)

                await asyncio.sleep(settings.build_delay)

            # -- Build corridors / paths -------------------------------------
            for idx, corridor in enumerate(placed.corridors, start=1):
                self._cmd(
                    _tellraw(
                        f"[NemoCraft] Building {connection_label} ({idx}/{total_corridors})...",
                        color="gold",
                    )
                )
                self._build_corridor(corridor)
                logger.info("Built %s %d/%d", connection_label, idx, total_corridors)

                await asyncio.sleep(settings.build_delay)

            self._cmd(
                _tellraw(
                    f'[NemoCraft] "{placed.name}" complete!',
                    color="green",
                )
            )
            logger.info(
                "Build complete: %s [%s] (%d %ss, %d %ss)",
                placed.name,
                structure_type,
                total_rooms,
                room_label,
                total_corridors,
                connection_label,
            )

        finally:
            self.disconnect()

        return {
            "name": placed.name,
            "room_count": total_rooms,
            "structure_type": structure_type,
        }
