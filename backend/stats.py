"""Player stats tracking with exponential decay for activity-based dungeon scaling."""

import json
import logging
import math
import time
from pathlib import Path
from pydantic import BaseModel, Field

from backend.karma import (
    KarmaState,
    KarmaTier,
    KARMA_ACTION_WEIGHTS,
    composite_score,
    score_to_tier,
    update_karma,
)

logger = logging.getLogger(__name__)

# Decay rates (lambda) per stat category
# combat decays faster (~14h half-life), exploration slower (~35h half-life)
DECAY_RATES = {
    "combat": 0.05,       # ~14h half-life
    "exploration": 0.02,  # ~35h half-life
    "building": 0.03,     # ~23h half-life
    "crafting": 0.03,     # ~23h half-life
}

STAT_CATEGORIES = {
    "mob_kills": "combat",
    "player_deaths": "combat",
    "damage_dealt": "combat",
    "damage_taken": "combat",
    "biomes_visited": "exploration",
    "distance_traveled": "exploration",
    "unique_structures_found": "exploration",
    "blocks_placed": "building",
    "blocks_broken": "building",
    "items_crafted": "crafting",
    "items_used": "crafting",
}

class StatSnapshot(BaseModel):
    """A snapshot of stats at a point in time."""
    timestamp: float = Field(default_factory=time.time)
    mob_kills: int = 0
    player_deaths: int = 0
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    biomes_visited: int = 0
    distance_traveled: float = 0.0
    unique_structures_found: int = 0
    blocks_placed: int = 0
    blocks_broken: int = 0
    items_crafted: int = 0
    items_used: int = 0

    # Karma counters — negative actions (passive/neutral mob kills)
    killed_villager: int = 0
    killed_iron_golem: int = 0
    killed_cat: int = 0
    killed_wolf: int = 0
    killed_dolphin: int = 0
    killed_horse: int = 0
    killed_donkey: int = 0
    killed_turtle: int = 0
    killed_bee: int = 0
    killed_cow: int = 0
    killed_pig: int = 0
    killed_sheep: int = 0
    killed_fox: int = 0
    killed_chicken: int = 0
    killed_rabbit: int = 0

    # Karma counters — positive actions
    raid_win: int = 0
    traded_with_villager: int = 0
    animals_bred: int = 0
    pot_flower: int = 0
    fish_caught: int = 0
    talked_to_villager: int = 0
    bell_ring: int = 0


def _decay(value: float, hours_elapsed: float, decay_rate: float) -> float:
    """Apply exponential decay: decayed = value * e^(-λ * hours)."""
    return value * math.exp(-decay_rate * hours_elapsed)


_KARMA_COUNTER_FIELDS: set[str] = set(KARMA_ACTION_WEIGHTS.keys())


class PlayerProfile:
    """Tracks a player's stats over time with exponential decay."""

    def __init__(self, player_uuid: str, data_dir: str = "player_data"):
        self.player_uuid = player_uuid
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots: list[StatSnapshot] = []
        self.karma: KarmaState = KarmaState()
        self._load()

    def _file_path(self) -> Path:
        return self.data_dir / f"{self.player_uuid}_stats.json"

    def _load(self) -> None:
        path = self._file_path()
        if path.exists():
            data = json.loads(path.read_text())
            self.snapshots = [StatSnapshot(**s) for s in data.get("snapshots", [])]
            if "karma" in data:
                self.karma = KarmaState(**data["karma"])

    def save(self) -> None:
        path = self._file_path()
        data = {
            "snapshots": [s.model_dump() for s in self.snapshots],
            "karma": self.karma.model_dump(),
        }
        path.write_text(json.dumps(data, indent=2))

    def add_snapshot(self, stats: dict) -> None:
        """Add a new stat snapshot from raw MC scoreboard data and update karma."""
        # Build snapshot from known fields (both legacy and karma counters)
        known_fields = set(STAT_CATEGORIES.keys()) | _KARMA_COUNTER_FIELDS
        snapshot = StatSnapshot(timestamp=time.time(), **{
            k: v for k, v in stats.items() if k in known_fields
        })
        self.snapshots.append(snapshot)

        # Update karma from current counters
        current_counters = {k: stats.get(k, 0) for k in _KARMA_COUNTER_FIELDS}
        self.karma = update_karma(self.karma, current_counters)
        logger.debug(
            "Karma updated for %s: v=%.1f n=%.1f s=%.1f (score=%.1f, tier=%s)",
            self.player_uuid, self.karma.violence, self.karma.nature,
            self.karma.social, self.get_karma_score(), self.get_karma_tier().value,
        )

        self.save()

    def get_decayed_stats(self) -> dict[str, float]:
        """Get current effective stats after applying exponential decay."""
        now = time.time()
        totals: dict[str, float] = {stat: 0.0 for stat in STAT_CATEGORIES}

        for snapshot in self.snapshots:
            hours_elapsed = (now - snapshot.timestamp) / 3600.0
            for stat_name, category in STAT_CATEGORIES.items():
                raw_value = getattr(snapshot, stat_name, 0)
                if raw_value:
                    decay_rate = DECAY_RATES[category]
                    totals[stat_name] += _decay(float(raw_value), hours_elapsed, decay_rate)

        return totals

    def get_playstyle(self) -> str:
        """Categorize player based on decayed stats: aggressive, explorer, builder, balanced."""
        stats = self.get_decayed_stats()

        combat_score = stats["mob_kills"] + stats["damage_dealt"] * 0.01
        explore_score = stats["biomes_visited"] * 10 + stats["distance_traveled"] * 0.001
        build_score = stats["blocks_placed"] * 0.1 + stats["blocks_broken"] * 0.05

        scores = {
            "aggressive": combat_score,
            "explorer": explore_score,
            "builder": build_score,
        }

        max_style = max(scores, key=scores.get)
        max_val = scores[max_style]

        # If no clear winner (top score < 2x others), call it balanced
        others = [v for k, v in scores.items() if k != max_style]
        if max_val < 1.0 or (others and max_val < 2 * max(others)):
            return "balanced"
        return max_style

    def get_intensity(self) -> float:
        """0.0-1.0 score of how active the player has been recently."""
        stats = self.get_decayed_stats()
        # Combine all decayed stats into a single intensity score
        raw = (
            stats["mob_kills"] * 2
            + stats["damage_dealt"] * 0.05
            + stats["blocks_placed"] * 0.1
            + stats["distance_traveled"] * 0.001
            + stats["items_crafted"] * 0.5
        )
        # Sigmoid-like mapping to 0-1 range
        return min(1.0, raw / 100.0)

    def get_karma_score(self) -> float:
        """Composite karma score: violence*0.3 + nature*0.3 + social*0.4."""
        return composite_score(self.karma)

    def get_karma_tier(self) -> KarmaTier:
        """Current karma tier based on composite score."""
        return score_to_tier(self.get_karma_score())
