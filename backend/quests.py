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
                    "destination_prompt": "A dark stone crypt infested with undead, deep underground with skull decorations and cobwebs",
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
                    "destination_prompt": "A grand gladiator arena with lava moat, stone brick walls, and spectator stands",
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
                    "destination_prompt": "An abandoned mineshaft overrun with cobwebs, spiders, and cave spider spawners",
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
                    "destination_prompt": "A hidden jungle temple with ancient traps, gold decorations, and mysterious enchanting rooms",
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
                    "destination_prompt": "A small wooden village under siege with barricades, watchtowers, and defensive walls",
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
                    "destination_prompt": "An underground river cavern with prismarine walls, water features, and glowing crystals",
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
                    "destination_prompt": "A crumbling ancient castle with missing walls, overgrown vines, and mossy stone bricks",
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
                    "destination_prompt": "A bustling marketplace with wooden stalls, colorful wool banners, and trading villagers",
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
                    "destination_type": "lighthouse",
                    "destination_prompt": "A tall stone lighthouse on a cliff with a spiral staircase and broken beacon room at the top",
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
                    "destination_prompt": "A sealed underground vault with iron doors, trapped corridors, and a treasure chamber",
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
                    "destination_prompt": "A cozy mountain cabin with a chimney, enchanting table, and bookshelves full of ancient tomes",
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
                    "destination_prompt": "A deep underground fissure with sculk blocks, cave spider spawners, and deepslate walls",
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
                    "destination_prompt": "A nether-themed burial crypt with soul sand, soul torches, and wither skeleton guardians",
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
                    "destination_prompt": "A mystical end-stone temple floating above a void with purpur pillars and ender creatures",
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
                    "destination_prompt": "A frontier fort with watchtowers, wooden palisades, and a central command tent",
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
                    "destination_prompt": "A vast underground library with towering bookshelves, enchanting tables, and candle-lit reading nooks",
                },
            ],
        }

        base_pool = pools.get(playstyle, pools["balanced"])
        extras = theme_extras.get(narrative_ctx.theme, [])
        return base_pool + extras
