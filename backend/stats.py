"""Player stats tracking with exponential decay for activity-based dungeon scaling."""

import json
import math
import time
from pathlib import Path
from pydantic import BaseModel, Field

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


def _decay(value: float, hours_elapsed: float, decay_rate: float) -> float:
    """Apply exponential decay: decayed = value * e^(-λ * hours)."""
    return value * math.exp(-decay_rate * hours_elapsed)


class PlayerProfile:
    """Tracks a player's stats over time with exponential decay."""

    def __init__(self, player_uuid: str, data_dir: str = "player_data"):
        self.player_uuid = player_uuid
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots: list[StatSnapshot] = []
        self._load()

    def _file_path(self) -> Path:
        return self.data_dir / f"{self.player_uuid}_stats.json"

    def _load(self) -> None:
        path = self._file_path()
        if path.exists():
            data = json.loads(path.read_text())
            self.snapshots = [StatSnapshot(**s) for s in data.get("snapshots", [])]

    def save(self) -> None:
        path = self._file_path()
        data = {"snapshots": [s.model_dump() for s in self.snapshots]}
        path.write_text(json.dumps(data, indent=2))

    def add_snapshot(self, stats: dict) -> None:
        """Add a new stat snapshot from raw MC scoreboard data."""
        snapshot = StatSnapshot(timestamp=time.time(), **{
            k: v for k, v in stats.items() if k in STAT_CATEGORIES
        })
        self.snapshots.append(snapshot)
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
