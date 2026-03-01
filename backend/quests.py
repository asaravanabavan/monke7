"""Quest system that uses Nemotron to generate dynamic quests based on the world.

Quests lead players to dungeons, villages, temples, and other generated structures.
They provide objectives (kill mobs, explore locations, collect items, etc.) with
rewards that scale based on difficulty and player behavior.
"""

import json
import random
import time
import uuid as uuid_lib
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.stats import PlayerProfile
from backend.narrative import NarrativeEngine, NarrativeContext


# ---------------------------------------------------------------------------
# Quest models
# ---------------------------------------------------------------------------

class QuestType(str, Enum):
    """Types of quest objectives."""
    KILL = "kill"                    # Kill specific mobs
    EXPLORE = "explore"              # Reach a location / dungeon
    COLLECT = "collect"              # Gather specific items
    ESCORT = "escort"                # Protect villagers / mobs
    BUILD = "build"                  # Place specific blocks
    SURVIVE = "survive"              # Survive waves in an arena
    CLEAR_DUNGEON = "clear_dungeon"  # Clear all mobs in a dungeon


class QuestStatus(str, Enum):
    """Quest lifecycle status."""
    AVAILABLE = "available"    # Generated, not yet accepted
    ACTIVE = "active"          # Player accepted it
    COMPLETED = "completed"    # Player finished objectives
    FAILED = "failed"          # Player died or timed out
    EXPIRED = "expired"        # Quest timed out without being accepted


class QuestObjective(BaseModel):
    """A single objective within a quest."""
    description: str = Field(..., description="Human-readable objective text")
    objective_type: QuestType = Field(..., description="Type of objective")
    target: str = Field(..., description="Target entity/item/location name")
    target_count: int = Field(default=1, ge=1, description="How many to kill/collect/etc")
    current_count: int = Field(default=0, ge=0, description="Current progress")

    @property
    def is_complete(self) -> bool:
        return self.current_count >= self.target_count


class QuestReward(BaseModel):
    """Rewards granted on quest completion."""
    items: list[str] = Field(default_factory=list, description="Item IDs to give")
    experience: int = Field(default=0, ge=0, description="XP points to award")
    structure_prompt: str = Field(
        default="",
        description="If set, triggers building this structure as a reward",
    )


class Quest(BaseModel):
    """A complete quest with objectives, rewards, and narrative context."""
    quest_id: str = Field(default_factory=lambda: str(uuid_lib.uuid4())[:8])
    name: str = Field(..., description="Evocative quest name")
    description: str = Field(..., description="Quest storyline / flavor text")
    giver: str = Field(
        default="A mysterious traveler",
        description="Who gives this quest (NPC name / entity)",
    )
    objectives: list[QuestObjective] = Field(..., min_length=1)
    rewards: QuestReward = Field(default_factory=QuestReward)
    destination_type: str = Field(
        default="dungeon",
        description="Type of structure to generate: dungeon, village, temple, etc.",
    )
    destination_prompt: str = Field(
        default="",
        description="Prompt to pass to the structure generator for the quest destination",
    )
    difficulty: int = Field(default=3, ge=1, le=10)
    status: QuestStatus = Field(default=QuestStatus.AVAILABLE)
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(
        default=0.0,
        description="Unix timestamp when quest expires (0 = no expiry)",
    )
    completed_at: float = Field(default=0.0)

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at

    @property
    def all_objectives_complete(self) -> bool:
        return all(obj.is_complete for obj in self.objectives)


class PlayerQuestLog(BaseModel):
    """Persistent quest log for a single player."""
    player_uuid: str
    active_quests: list[Quest] = Field(default_factory=list)
    completed_quests: list[Quest] = Field(default_factory=list)
    total_quests_completed: int = 0


# ---------------------------------------------------------------------------
# Quest engine
# ---------------------------------------------------------------------------

# Maximum active quests per player
_MAX_ACTIVE_QUESTS = 3

# Quest expiry time: 2 hours (in seconds)
_QUEST_EXPIRY_SECONDS = 2 * 60 * 60


class QuestEngine:
    """Generates and manages quests for players.

    Uses Nemotron to create contextual quests based on the player's stats,
    narrative history, and play-style. Quests lead players to generated
    structures (dungeons, villages, temples, etc.).
    """

    def __init__(self, data_dir: str = "player_data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._narrative_engine = NarrativeEngine(data_dir=data_dir)

    # -- persistence --------------------------------------------------------

    def _quest_log_path(self, player_uuid: str) -> Path:
        return self.data_dir / f"{player_uuid}_quests.json"

    def load_quest_log(self, player_uuid: str) -> PlayerQuestLog:
        path = self._quest_log_path(player_uuid)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                log = PlayerQuestLog(**data)
                # Expire old quests
                self._expire_quests(log)
                return log
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        return PlayerQuestLog(player_uuid=player_uuid)

    def save_quest_log(self, log: PlayerQuestLog) -> None:
        path = self._quest_log_path(log.player_uuid)
        path.write_text(json.dumps(log.model_dump(), indent=2))

    def _expire_quests(self, log: PlayerQuestLog) -> None:
        """Move expired quests out of active list."""
        still_active = []
        for quest in log.active_quests:
            if quest.is_expired and quest.status in (QuestStatus.AVAILABLE, QuestStatus.ACTIVE):
                quest.status = QuestStatus.EXPIRED
            else:
                still_active.append(quest)
        log.active_quests = still_active

    # -- quest generation ---------------------------------------------------

    async def generate_quests(
        self,
        player_uuid: str,
        player_name: str = "Adventurer",
        player_x: float = 0,
        player_y: float = 64,
        player_z: float = 0,
    ) -> list[Quest]:
        """Generate new quests for a player using Nemotron.

        Considers the player's stats, play-style, and narrative history
        to create contextual quests that lead to generated structures.
        """
        log = self.load_quest_log(player_uuid)

        # Don't generate if player already has max active quests
        active_count = len([
            q for q in log.active_quests
            if q.status in (QuestStatus.AVAILABLE, QuestStatus.ACTIVE)
        ])
        if active_count >= _MAX_ACTIVE_QUESTS:
            return []

        # Build context from player data
        profile = PlayerProfile(player_uuid, data_dir=str(self.data_dir))
        decayed_stats = profile.get_decayed_stats()
        playstyle = profile.get_playstyle()
        intensity = profile.get_intensity()
        narrative_ctx = self._narrative_engine.build_context(player_uuid, player_name)

        # Get completed quest names to avoid repeats
        recent_completed = [q.name for q in log.completed_quests[-10:]]

        # How many quests to generate (fill up to max)
        slots = _MAX_ACTIVE_QUESTS - active_count
        num_quests = min(slots, random.randint(1, 3))

        # Call Nemotron to generate quests
        from backend.nemotron import generate_quests as nemotron_generate_quests

        try:
            quests = await nemotron_generate_quests(
                player_name=player_name,
                playstyle=playstyle,
                intensity=intensity,
                narrative_context=narrative_ctx.model_dump(),
                num_quests=num_quests,
                recent_completed=recent_completed,
            )
        except Exception:
            # Fallback to locally generated quests
            quests = self._generate_fallback_quests(
                player_name, playstyle, narrative_ctx, num_quests,
            )

        # Set expiry and add to quest log
        for quest in quests:
            quest.expires_at = time.time() + _QUEST_EXPIRY_SECONDS
            quest.difficulty = narrative_ctx.difficulty_level
            log.active_quests.append(quest)

        self.save_quest_log(log)
        return quests

    # -- quest actions ------------------------------------------------------

    def accept_quest(self, player_uuid: str, quest_id: str) -> Optional[Quest]:
        """Mark a quest as accepted by the player."""
        log = self.load_quest_log(player_uuid)
        for quest in log.active_quests:
            if quest.quest_id == quest_id and quest.status == QuestStatus.AVAILABLE:
                quest.status = QuestStatus.ACTIVE
                self.save_quest_log(log)
                return quest
        return None

    def update_progress(
        self,
        player_uuid: str,
        objective_type: QuestType,
        target: str,
        count: int = 1,
    ) -> list[Quest]:
        """Update progress on all active quests matching the objective.

        Returns list of quests that were fully completed by this update.
        """
        log = self.load_quest_log(player_uuid)
        newly_completed = []

        for quest in log.active_quests:
            if quest.status != QuestStatus.ACTIVE:
                continue

            for obj in quest.objectives:
                if (obj.objective_type == objective_type
                        and obj.target.lower() == target.lower()
                        and not obj.is_complete):
                    obj.current_count = min(
                        obj.current_count + count,
                        obj.target_count,
                    )

            if quest.all_objectives_complete:
                quest.status = QuestStatus.COMPLETED
                quest.completed_at = time.time()
                log.total_quests_completed += 1
                newly_completed.append(quest)

        # Move completed quests to completed list
        still_active = []
        for quest in log.active_quests:
            if quest.status == QuestStatus.COMPLETED:
                log.completed_quests.append(quest)
            else:
                still_active.append(quest)
        log.active_quests = still_active

        self.save_quest_log(log)
        return newly_completed

    def get_active_quests(self, player_uuid: str) -> list[Quest]:
        """Return all active/available quests for a player."""
        log = self.load_quest_log(player_uuid)
        return [
            q for q in log.active_quests
            if q.status in (QuestStatus.AVAILABLE, QuestStatus.ACTIVE)
        ]

    def fail_quest(self, player_uuid: str, quest_id: str) -> Optional[Quest]:
        """Mark a quest as failed."""
        log = self.load_quest_log(player_uuid)
        for quest in log.active_quests:
            if quest.quest_id == quest_id and quest.status == QuestStatus.ACTIVE:
                quest.status = QuestStatus.FAILED
                log.active_quests.remove(quest)
                self.save_quest_log(log)
                return quest
        return None

    # -- fallback quest generation ------------------------------------------

    def _generate_fallback_quests(
        self,
        player_name: str,
        playstyle: str,
        narrative_ctx: NarrativeContext,
        num_quests: int,
    ) -> list[Quest]:
        """Generate quests locally when Nemotron is unavailable."""
        quests = []
        pool = self._get_quest_pool(playstyle, narrative_ctx)
        selected = random.sample(pool, min(num_quests, len(pool)))

        for template in selected:
            quest = Quest(
                name=template["name"].format(player_name=player_name),
                description=template["description"].format(player_name=player_name),
                giver=template["giver"],
                objectives=[
                    QuestObjective(**obj) for obj in template["objectives"]
                ],
                rewards=QuestReward(**template["rewards"]),
                destination_type=template["destination_type"],
                destination_prompt=template["destination_prompt"],
                difficulty=narrative_ctx.difficulty_level,
            )
            quests.append(quest)

        return quests

    @staticmethod
    def _get_quest_pool(
        playstyle: str,
        narrative_ctx: NarrativeContext,
    ) -> list[dict]:
        """Return a pool of quest templates based on playstyle and theme."""
        pools = {
            "aggressive": [
                {
                    "name": "The Warlord's Bounty",
                    "description": "A warlord has placed a bounty on the undead lurking in a nearby crypt. Clear them out and claim the reward.",
                    "giver": "Captain Ironhelm",
                    "objectives": [
                        {"description": "Slay zombies in the crypt", "objective_type": "kill", "target": "minecraft:zombie", "target_count": 10},
                        {"description": "Slay the skeleton archers", "objective_type": "kill", "target": "minecraft:skeleton", "target_count": 5},
                    ],
                    "rewards": {"items": ["minecraft:diamond_sword", "minecraft:golden_apple"], "experience": 500},
                    "destination_type": "dungeon",
                    "destination_prompt": (
                        "A multi-room stone brick crypt with 3-4 rooms connected by narrow corridors. "
                        "First room: entrance hall with cracked stone brick pillars, iron bar windows, and skull decorations on the walls. "
                        "Second room: a large burial chamber with cobweb-covered ceiling, soul torches in alcoves, bone block floor accents, "
                        "and skeleton spawners behind iron bars. Third room: the warlord's tomb — a grand vaulted chamber with "
                        "a central sarcophagus made of gold blocks, chains hanging from the ceiling, and loot chests on either side. "
                        "Use deepslate bricks for lower walls, cracked stone bricks for upper walls, and polished blackstone for floors."
                    ),
                },
                {
                    "name": "Arena of Blood",
                    "description": "The fighting pits demand a champion. Survive the waves and earn glory.",
                    "giver": "The Arena Master",
                    "objectives": [
                        {"description": "Survive the arena waves", "objective_type": "survive", "target": "arena", "target_count": 1},
                        {"description": "Defeat hostile mobs", "objective_type": "kill", "target": "minecraft:zombie", "target_count": 15},
                    ],
                    "rewards": {"items": ["minecraft:diamond_chestplate", "minecraft:enchanted_golden_apple"], "experience": 800},
                    "destination_type": "arena",
                    "destination_prompt": (
                        "A grand circular gladiator arena with 3 rooms. Main arena: a large open-air colosseum (25x10x25) "
                        "with a sunken fighting pit 2 blocks deep, lava channels around the perimeter, iron bar cages "
                        "on the walls with zombie and skeleton spawners inside, stone brick spectator stands rising in tiers, "
                        "red wool banners on pillars, and campfire braziers at each corner. Armory room: weapon racks made of "
                        "anvils and armor stands, chests with combat loot. Champion's hall: a throne of gold blocks and "
                        "stairs with a red carpet leading to it, diamond block trophy pedestals, and hanging lanterns with chains."
                    ),
                },
                {
                    "name": "The Spider Queen's Lair",
                    "description": "Giant spiders have overrun an abandoned mine. The villagers beg for your help.",
                    "giver": "Elder Willowbrook",
                    "objectives": [
                        {"description": "Clear the spider infestation", "objective_type": "kill", "target": "minecraft:spider", "target_count": 8},
                        {"description": "Destroy the spider spawner", "objective_type": "clear_dungeon", "target": "spawner_room", "target_count": 1},
                    ],
                    "rewards": {"items": ["minecraft:bow", "minecraft:arrow", "minecraft:iron_sword"], "experience": 400},
                    "destination_type": "mine",
                    "destination_prompt": (
                        "An abandoned mineshaft dungeon with 3-4 rooms connected by narrow tunnels. Entry shaft: "
                        "cobblestone and oak plank walls with broken minecart tracks (rail blocks), scattered torches, "
                        "and cobwebs in every corner. Mining gallery: a tall room with oak log support pillars, "
                        "ore block veins (iron, coal, gold) exposed in the deepslate walls, broken ladders, and "
                        "cave spider spawners hidden behind cobweb clusters. Spider nest: the deepest room with "
                        "walls entirely covered in cobwebs, white wool egg sacs on the floor, soul torches for eerie "
                        "blue lighting, and a massive cobweb canopy across the ceiling with spiders and cave spiders."
                    ),
                },
            ],
            "explorer": [
                {
                    "name": "The Lost Temple",
                    "description": "Ancient maps point to a forgotten temple deep in the wilderness. Discover its secrets.",
                    "giver": "Scholar Meridia",
                    "objectives": [
                        {"description": "Find the Lost Temple", "objective_type": "explore", "target": "lost_temple", "target_count": 1},
                        {"description": "Collect the ancient relic", "objective_type": "collect", "target": "minecraft:totem_of_undying", "target_count": 1},
                    ],
                    "rewards": {"items": ["minecraft:spyglass", "minecraft:compass", "minecraft:diamond"], "experience": 600},
                    "destination_type": "temple",
                    "destination_prompt": (
                        "A hidden jungle temple complex with 3-4 rooms in a circular layout. Entrance courtyard: "
                        "mossy cobblestone walls with vine overgrowth, chiseled stone brick pillars forming a colonnade, "
                        "a central fountain made of water and prismarine, and flower pots with ferns. Inner sanctum: "
                        "tall ceiling (12+ blocks) with gold block accents, enchanting tables on pedestals, "
                        "end rod lighting along the walls, lecterns with books, candle clusters on the floor, "
                        "and stained glass (colored glass panes) in the walls. Trap corridor: pressure plates connected "
                        "to dispensers, tripwire, and arrow slits (iron bars) in the walls. Treasure vault: "
                        "a small room with chiseled stone bricks, a loot chest on a gold block pedestal, "
                        "iron golems as guardians, and emerald block decorations."
                    ),
                },
                {
                    "name": "Village in Peril",
                    "description": "A distant village sends word of a pillager siege. Reach them before it's too late.",
                    "giver": "A desperate messenger",
                    "objectives": [
                        {"description": "Reach the besieged village", "objective_type": "explore", "target": "besieged_village", "target_count": 1},
                        {"description": "Defeat the pillagers", "objective_type": "kill", "target": "minecraft:pillager", "target_count": 6},
                    ],
                    "rewards": {"items": ["minecraft:emerald", "minecraft:golden_apple", "minecraft:iron_ingot"], "experience": 500},
                    "destination_type": "village",
                    "destination_prompt": (
                        "A besieged village settlement with 4-5 buildings in a cluster layout connected by gravel paths. "
                        "Blacksmith forge: stone brick walls, furnaces, anvils, lava source as the forge, iron bars on windows, "
                        "and a peaked oak plank roof. Town hall: the largest building with oak log framing, cobblestone base, "
                        "peaked roof, a bell in the entrance, bookshelves, a crafting table, and a lectern. "
                        "Farmstead: oak plank walls with a fence perimeter and garden exterior, hay bales inside, "
                        "a composting area, wheat crops nearby. Guard tower: a tall 3-story cobblestone watchtower with "
                        "peaked roof, crossbow slits (iron bars), lanterns on each floor, and a lookout platform. "
                        "All buildings should have windows (glass panes), doors, and warm lighting (lanterns, torches). "
                        "Villagers, cats, and an iron golem should populate the village. Pillagers lurk outside."
                    ),
                },
                {
                    "name": "Cartographer's Challenge",
                    "description": "A cartographer needs someone brave enough to chart the underground river system.",
                    "giver": "Cartographer Finch",
                    "objectives": [
                        {"description": "Explore the underground river", "objective_type": "explore", "target": "underground_river", "target_count": 1},
                        {"description": "Collect glowstone samples", "objective_type": "collect", "target": "minecraft:glowstone_dust", "target_count": 5},
                    ],
                    "rewards": {"items": ["minecraft:map", "minecraft:diamond", "minecraft:ender_pearl"], "experience": 450},
                    "destination_type": "dungeon",
                    "destination_prompt": (
                        "An underground river cavern system with 3 rooms connected by flooded corridors. "
                        "Entry grotto: prismarine and stone walls with water pools on the floor, sea lantern "
                        "lighting embedded in walls, glowstone veins in the ceiling, and dripping chains. "
                        "River chamber: a wide room with a water channel running through the center, "
                        "prismarine brick bridges crossing it, coral blocks and sea pickles along the waterline, "
                        "and dark prismarine pillars supporting a mossy ceiling. Crystal cavern: the deepest room "
                        "with amethyst block clusters, glowstone formations, a central pool with soul lanterns "
                        "beneath the water, and a cartography table with map chests on the shore."
                    ),
                },
            ],
            "builder": [
                {
                    "name": "The Architect's Trial",
                    "description": "The Master Builder's guild seeks a worthy apprentice. Prove yourself by restoring a ruined castle.",
                    "giver": "Guildmaster Ashford",
                    "objectives": [
                        {"description": "Reach the ruined castle", "objective_type": "explore", "target": "ruined_castle", "target_count": 1},
                        {"description": "Place restoration blocks", "objective_type": "build", "target": "minecraft:stone_bricks", "target_count": 50},
                    ],
                    "rewards": {"items": ["minecraft:diamond_pickaxe", "minecraft:emerald", "minecraft:lantern"], "experience": 500},
                    "destination_type": "castle",
                    "destination_prompt": (
                        "A crumbling medieval castle with 3 rooms in a linear layout. Gatehouse: stone brick walls with "
                        "mossy stone brick patches, cracked stone bricks showing age, iron bar portcullis, a flat roof "
                        "with battlements, arrow slits in the walls, and defensive wall exterior. Courtyard hall: "
                        "a large open room with broken stone brick pillars (some only 2-3 blocks tall), vine-covered "
                        "walls, mossy cobblestone floor with grass patches, a crumbled section where wall blocks are "
                        "missing, and scattered cobblestone debris (detail blocks). Ruined throne room: the back chamber "
                        "with a partially collapsed ceiling (air holes with vines hanging through), a damaged throne "
                        "made of stairs and gold blocks, faded red wool carpet remnants, and cobweb-filled alcoves "
                        "where banners once hung. Use mixed stone brick variants throughout for a weathered look."
                    ),
                },
                {
                    "name": "Marketplace Mayhem",
                    "description": "A new trading post needs building materials. Gather what's needed and deliver them.",
                    "giver": "Merchant Goldweave",
                    "objectives": [
                        {"description": "Collect oak planks", "objective_type": "collect", "target": "minecraft:oak_planks", "target_count": 64},
                        {"description": "Deliver to the marketplace", "objective_type": "explore", "target": "marketplace", "target_count": 1},
                    ],
                    "rewards": {"items": ["minecraft:emerald", "minecraft:diamond", "minecraft:iron_ingot"], "experience": 350},
                    "destination_type": "marketplace",
                    "destination_prompt": (
                        "A bustling marketplace with 4-5 small buildings in a grid layout connected by cobblestone paths. "
                        "General store: spruce plank walls with oak log corners, peaked roof, glass pane windows, "
                        "a door with a porch, barrels and chests inside with trade goods, lantern lighting. "
                        "Bakery: a small brick building with a furnace, crafting table, flower pots on windowsills, "
                        "and hay bale storage. Weapon shop: stone brick base with dark oak upper walls, anvils inside, "
                        "iron bar displays, and armor stands. Town well: a tiny cobblestone structure with a "
                        "cauldron of water, chain and fence post above it, and flower gardens around it. "
                        "Each building should have a peaked roof, windows, doors, and a fence or garden exterior. "
                        "Populate with villagers, cats, and wandering traders. Wool banners of different colors "
                        "on fence posts mark each stall."
                    ),
                },
                {
                    "name": "The Lighthouse Keeper",
                    "description": "The old lighthouse on the coast has gone dark. Rebuild the beacon before ships are lost.",
                    "giver": "Harbormaster Tidewell",
                    "objectives": [
                        {"description": "Find the abandoned lighthouse", "objective_type": "explore", "target": "lighthouse", "target_count": 1},
                        {"description": "Place glowstone to relight the beacon", "objective_type": "build", "target": "minecraft:glowstone", "target_count": 16},
                    ],
                    "rewards": {"items": ["minecraft:spyglass", "minecraft:lantern", "minecraft:golden_apple"], "experience": 400},
                    "destination_type": "tower",
                    "destination_prompt": (
                        "A tall coastal lighthouse tower (height 16-20 blocks) with 3-4 floors. Built from stone bricks "
                        "with a white concrete stripe pattern. Ground floor: a keeper's quarters with a furnace, bed "
                        "(wool blocks), bookshelf, crafting table, and a spiral staircase up (oak stairs wrapping the "
                        "interior wall). Middle floors: storage rooms with barrels, chests of supplies, iron bar windows "
                        "looking outward, and lantern wall sconces. Top floor: the beacon room — a domed roof with "
                        "glowstone and sea lantern blocks forming the light, glass pane walls on all sides for "
                        "360-degree visibility, a railing of fences around an exterior walkway, and a spyglass on a "
                        "lectern. The exterior should have a peaked or dome roof and a fence walkway at the top level."
                    ),
                },
            ],
            "balanced": [
                {
                    "name": "The Forgotten Vault",
                    "description": "Rumors speak of a vault beneath the hills, sealed for centuries. What treasures await within?",
                    "giver": "Old Man Graybeard",
                    "objectives": [
                        {"description": "Discover the Forgotten Vault", "objective_type": "explore", "target": "forgotten_vault", "target_count": 1},
                        {"description": "Defeat the vault guardians", "objective_type": "kill", "target": "minecraft:zombie", "target_count": 5},
                        {"description": "Claim the vault treasure", "objective_type": "collect", "target": "minecraft:diamond", "target_count": 3},
                    ],
                    "rewards": {"items": ["minecraft:diamond_sword", "minecraft:golden_apple", "minecraft:emerald"], "experience": 600},
                    "destination_type": "dungeon",
                    "destination_prompt": (
                        "A sealed underground vault dungeon with 3-4 rooms in a linear layout. Entrance chamber: "
                        "iron door frame with chiseled stone bricks, pressure plate traps, skeleton archers in "
                        "alcoves behind iron bars, and dim lantern lighting on chains. Trap corridor: a narrow passage "
                        "with dispensers hidden in walls, tripwire, cobwebs across the ceiling, and scattered bone "
                        "blocks from previous adventurers. Guard room: polished deepslate floor, deepslate brick walls, "
                        "zombie spawners behind iron bar cages, weapon racks (anvils), and armor display alcoves. "
                        "Treasury: the final room with polished blackstone floor, gold block pedestals displaying loot "
                        "chests, diamond block accents, emerald block pillars, lanterns hanging from chains at multiple "
                        "heights, and a grand central chest on an elevated platform of quartz stairs."
                    ),
                },
                {
                    "name": "The Hermit's Request",
                    "description": "A hermit living in the mountains needs supplies. He promises ancient knowledge in return.",
                    "giver": "The Mountain Hermit",
                    "objectives": [
                        {"description": "Find the hermit's cabin", "objective_type": "explore", "target": "hermit_cabin", "target_count": 1},
                        {"description": "Deliver food supplies", "objective_type": "collect", "target": "minecraft:bread", "target_count": 10},
                    ],
                    "rewards": {"items": ["minecraft:enchanted_golden_apple", "minecraft:ender_pearl"], "experience": 300},
                    "destination_type": "house",
                    "destination_prompt": (
                        "A cozy 2-story mountain cabin. Ground floor: spruce plank walls with spruce log corner "
                        "pillars, cobblestone foundation, a peaked spruce roof, glass pane windows on all sides, "
                        "a door with a porch exterior. Interior: a furnace and campfire as the hearth against one wall, "
                        "a crafting table, bookshelves lining two walls floor to ceiling, a lectern with a book, "
                        "flower pots on windowsills, a red wool and white wool bed, and warm lantern lighting. "
                        "Second floor: an enchanting room with an enchanting table surrounded by bookshelves, "
                        "brewing stands, candle clusters, and a balcony (fence railing) overlooking the entrance. "
                        "Garden exterior with fence perimeter, composters, flower pots, and a small animal pen."
                    ),
                },
                {
                    "name": "Echoes of the Deep",
                    "description": "Strange sounds emanate from a fissure in the earth. Investigate the source.",
                    "giver": "A frightened miner",
                    "objectives": [
                        {"description": "Descend into the fissure", "objective_type": "explore", "target": "deep_fissure", "target_count": 1},
                        {"description": "Defeat the creatures below", "objective_type": "kill", "target": "minecraft:cave_spider", "target_count": 8},
                    ],
                    "rewards": {"items": ["minecraft:diamond_pickaxe", "minecraft:iron_ingot", "minecraft:torch"], "experience": 450},
                    "destination_type": "dungeon",
                    "destination_prompt": (
                        "A deep underground fissure dungeon with 3 rooms descending deeper. Upper cavern: "
                        "cobbled deepslate walls with sculk patches growing along the floor, dim soul torches, "
                        "chain bridges crossing gaps, and stalactite-like chains hanging from the ceiling. "
                        "Spider den: deepslate tile walls completely draped in cobwebs, cave spider spawners hidden "
                        "in alcoves, bone block scattered on the floor, skull decorations on walls, and mushroom "
                        "blocks growing in dark corners. Sculk chamber: the deepest room with sculk blocks covering "
                        "the floor and climbing the walls, sculk veins as detail blocks, deepslate brick pillars, "
                        "soul lanterns casting blue light, a central pit with chains crossing over it, and a "
                        "treasure chest on a deepslate pedestal at the far end."
                    ),
                },
            ],
        }

        # Merge theme-specific extras
        theme_extras = {
            "retribution": [
                {
                    "name": "Vengeance Calls",
                    "description": "The spirits of fallen warriors demand justice. Enter their burial ground and put them to rest.",
                    "giver": "The Spirit Warden",
                    "objectives": [
                        {"description": "Enter the burial ground", "objective_type": "explore", "target": "burial_ground", "target_count": 1},
                        {"description": "Defeat restless spirits", "objective_type": "kill", "target": "minecraft:phantom", "target_count": 5},
                    ],
                    "rewards": {"items": ["minecraft:diamond_sword", "minecraft:golden_apple"], "experience": 500},
                    "destination_type": "dungeon",
                    "destination_prompt": (
                        "A nether-themed burial crypt with 3 rooms. Mourning hall: blackstone walls with "
                        "soul sand floor strips, soul torches in wall brackets, wither skull decorations, "
                        "chains hanging from the ceiling, and polished blackstone slab coffins along the walls. "
                        "Crematorium: nether brick walls with magma block floor accents, lava source blocks behind "
                        "iron bars creating an orange glow, bone block pyres, and crimson fence railings. "
                        "Warden's sanctum: polished blackstone floor with gold block inlays, a central altar "
                        "of crying obsidian, soul lanterns in all corners, wither skeleton guardians, "
                        "and a loot chest flanked by respawn anchor blocks."
                    ),
                },
            ],
            "discovery": [
                {
                    "name": "Beyond the Horizon",
                    "description": "A shimmering portal has appeared in the wilderness. Step through and discover what lies beyond.",
                    "giver": "A wandering sage",
                    "objectives": [
                        {"description": "Find the mysterious portal", "objective_type": "explore", "target": "portal_site", "target_count": 1},
                        {"description": "Collect end crystals", "objective_type": "collect", "target": "minecraft:ender_pearl", "target_count": 4},
                    ],
                    "rewards": {"items": ["minecraft:elytra", "minecraft:ender_pearl"], "experience": 700},
                    "destination_type": "temple",
                    "destination_prompt": (
                        "A mystical end-themed temple with 3 rooms in a circular layout. Portal chamber: "
                        "purpur block walls with end stone brick accents, end rod lighting columns from "
                        "floor to ceiling, a central obsidian platform with ender pearl item frames, and "
                        "shulker guardians on the walls. Observatory: a tall domed room with purple stained glass "
                        "ceiling, purpur pillars, enchanting tables on quartz pedestals, and end rod chandeliers. "
                        "Vault of echoes: end stone brick floor with purpur slab patterns, chorus plant "
                        "decorations in corners, a dragon head on the back wall, and diamond block and "
                        "emerald block trophy cases with loot chests."
                    ),
                },
            ],
            "invasion": [
                {
                    "name": "Defend the Outpost",
                    "description": "Your building activity has drawn attention. An outpost must be fortified before the horde arrives.",
                    "giver": "Scout Hawkeye",
                    "objectives": [
                        {"description": "Reach the frontier outpost", "objective_type": "explore", "target": "frontier_outpost", "target_count": 1},
                        {"description": "Place defensive blocks", "objective_type": "build", "target": "minecraft:cobblestone", "target_count": 30},
                        {"description": "Repel the invaders", "objective_type": "kill", "target": "minecraft:vindicator", "target_count": 6},
                    ],
                    "rewards": {"items": ["minecraft:diamond_chestplate", "minecraft:crossbow"], "experience": 650},
                    "destination_type": "fort",
                    "destination_prompt": (
                        "A frontier military fort with 3 buildings in a cluster layout connected by gravel paths. "
                        "Command tent: a large spruce plank building with a flat roof, cobblestone foundation, "
                        "a war table (cartography table), banners (wool blocks), weapon racks (anvils), and "
                        "a strategic map (lectern). Barracks: a long building with rows of beds (wool blocks), "
                        "chests of supplies, furnaces, crafting tables, and armor stands. Watchtower: a 3-story "
                        "cobblestone tower with a flat roof and battlement exterior, iron bar arrow slits, "
                        "a ladder system between floors, crossbow storage, and a bell at the top. "
                        "Surround with a fence palisade wall with torch-lit gate posts. "
                        "Place iron golems and villagers as garrison defenders."
                    ),
                },
            ],
            "mystery": [
                {
                    "name": "The Whispering Library",
                    "description": "Books in the old library turn their own pages. Something ancient wants to be read.",
                    "giver": "Librarian Inkwell",
                    "objectives": [
                        {"description": "Find the Whispering Library", "objective_type": "explore", "target": "whispering_library", "target_count": 1},
                        {"description": "Collect enchanted books", "objective_type": "collect", "target": "minecraft:book", "target_count": 5},
                    ],
                    "rewards": {"items": ["minecraft:enchanted_golden_apple", "minecraft:book", "minecraft:emerald"], "experience": 500},
                    "destination_type": "library",
                    "destination_prompt": (
                        "A vast underground library with 3-4 rooms in a linear layout. Grand reading hall: "
                        "a tall room (height 12+) with floor-to-ceiling bookshelves (3-4 blocks high) along "
                        "every wall, dark oak plank floor with carpet (wool) runners, enchanting tables on "
                        "oak pedestals in the center, lecterns with books at reading desks, candle clusters "
                        "on every surface, and chain-hung lanterns from the ceiling. Archive wing: narrower "
                        "corridors lined with bookshelves, cobweb-covered alcoves with rare book chests, "
                        "iron bar locked sections, and soul torches for eerie lighting. Study chamber: "
                        "a circular room with a domed ceiling, a central enchanting table surrounded by "
                        "maximum bookshelves, brewing stands in one corner, an alchemy station, "
                        "and candles everywhere. The walls use dark oak planks with stone brick foundations."
                    ),
                },
            ],
        }

        base_pool = pools.get(playstyle, pools["balanced"])
        extras = theme_extras.get(narrative_ctx.theme, [])
        return base_pool + extras
