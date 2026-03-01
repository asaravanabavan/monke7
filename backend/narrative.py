"""Evolving narrative engine that generates story context based on player behavior.

Determines dungeon theme, difficulty, mood, loot quality, and mob density from
a player's decayed stats and play-style. Maintains per-player narrative history
so that successive dungeons feel like a continuous story arc.
"""

import json
import random
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.stats import PlayerProfile


# ---------------------------------------------------------------------------
# Narrative context model
# ---------------------------------------------------------------------------

class NarrativeContext(BaseModel):
    """Complete narrative parameters for a single dungeon generation."""

    theme: str = Field(
        ...,
        description="Overall dungeon theme, e.g. retribution, discovery, invasion, mystery",
    )
    mood: str = Field(
        ...,
        description="Atmospheric mood string, e.g. dark, mysterious, foreboding, ancient",
    )
    difficulty_level: int = Field(
        ..., ge=1, le=10,
        description="Difficulty on a 1-10 scale",
    )
    story_hook: str = Field(
        ...,
        description="One-sentence story intro for the dungeon",
    )
    loot_quality: float = Field(
        ..., ge=0.5, le=2.0,
        description="Loot quality multiplier (0.5-2.0)",
    )
    mob_count_multiplier: float = Field(
        ..., ge=0.5, le=2.0,
        description="Mob count multiplier (0.5-2.0)",
    )


# ---------------------------------------------------------------------------
# Theme / mood / hook data
# ---------------------------------------------------------------------------

_THEME_MOODS: dict[str, str] = {
    "retribution": "dark",
    "discovery": "mysterious",
    "invasion": "foreboding",
    "mystery": "ancient",
}

_THEME_TAGLINES: dict[str, str] = {
    "retribution": "The land cries for justice",
    "discovery": "A forgotten realm reveals itself",
    "invasion": "Your creations attract attention",
    "mystery": "Something stirs in the unknown",
}

_STORY_HOOKS: dict[str, list[str]] = {
    "retribution": [
        "Vengeful spirits have risen to challenge {player_name} in the depths below.",
        "The fallen demand retribution, and {player_name} must answer their call.",
        "Blood-soaked corridors await {player_name} — the earth remembers every kill.",
        "A dark force, born from countless battles, beckons {player_name} underground.",
        "The restless dead whisper {player_name}'s name through the crypt walls.",
    ],
    "discovery": [
        "{player_name} stumbles upon a passage that no map has ever charted.",
        "Ancient runes glow at {player_name}'s approach, revealing a hidden sanctum.",
        "The horizon was never the limit — {player_name} finds a world beneath the world.",
        "A long-sealed doorway creaks open as {player_name} draws near.",
        "Legends spoke of this place, but only {player_name} dared to seek it.",
    ],
    "invasion": [
        "Something has noticed {player_name}'s constructions and now answers in kind.",
        "The creatures below have grown envious of {player_name}'s creations.",
        "{player_name}'s building activity has breached an ancient seal.",
        "Drawn by the sound of industry, a subterranean horde awakens near {player_name}.",
        "The ground shifts beneath {player_name}'s foundations — something is tunneling up.",
    ],
    "mystery": [
        "A strange fog rolls in as {player_name} discovers an unmarked entrance.",
        "{player_name} hears a melody from deep underground — haunting and irresistible.",
        "Cryptic symbols appear overnight near {player_name}'s last known location.",
        "An old journal, found in the rubble, speaks of {player_name} by name.",
        "The compass spins wildly, guiding {player_name} toward an impossible place.",
    ],
}

_CONTINUITY_HOOKS: list[str] = [
    "After conquering {prev_dungeon}, a new challenge awaits {player_name}...",
    "The echoes of {prev_dungeon} still linger as {player_name} faces a fresh trial...",
    "Victory in {prev_dungeon} was only the beginning for {player_name}...",
    "Word of {player_name}'s triumph in {prev_dungeon} has spread, drawing new dangers...",
    "The secrets uncovered in {prev_dungeon} have led {player_name} here...",
]


# ---------------------------------------------------------------------------
# Scaling constants
# ---------------------------------------------------------------------------

_BASE_DIFFICULTY: int = 3
_DIFFICULTY_MULTIPLIER: int = 7


# ---------------------------------------------------------------------------
# Narrative engine
# ---------------------------------------------------------------------------

class NarrativeEngine:
    """Generates story context for dungeon generation from player behavior data.

    Parameters
    ----------
    data_dir:
        Root directory for persistent player data.  Defaults to ``"player_data"``.
    """

    def __init__(self, data_dir: str = "player_data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # -- public API ---------------------------------------------------------

    def build_context(
        self,
        player_uuid: str,
        player_name: str = "Adventurer",
    ) -> NarrativeContext:
        """Build a full :class:`NarrativeContext` for a dungeon generation run.

        1. Load the player profile and compute decayed stats.
        2. Determine theme from dominant stat category.
        3. Compute difficulty from recent intensity.
        4. Derive loot quality and mob density from difficulty.
        5. Generate a story hook (with continuity if history exists).
        """
        profile = PlayerProfile(player_uuid, data_dir=str(self.data_dir))
        decayed = profile.get_decayed_stats()
        intensity = profile.get_intensity()

        theme = self._determine_theme(decayed)
        mood = _THEME_MOODS.get(theme, "ancient")
        difficulty = self._compute_difficulty(intensity)
        loot_quality = self._compute_loot_quality(difficulty)
        mob_multiplier = self._compute_mob_multiplier(difficulty)
        story_hook = self._generate_story_hook(player_uuid, player_name, theme)

        return NarrativeContext(
            theme=theme,
            mood=mood,
            difficulty_level=difficulty,
            story_hook=story_hook,
            loot_quality=loot_quality,
            mob_count_multiplier=mob_multiplier,
        )

    def save_dungeon_record(
        self,
        player_uuid: str,
        dungeon_name: str,
        theme: str,
    ) -> None:
        """Persist a completed dungeon entry to the player's narrative history."""
        history = self._load_history(player_uuid)
        history.append({"dungeon_name": dungeon_name, "theme": theme})
        self._save_history(player_uuid, history)

    # -- theme determination ------------------------------------------------

    @staticmethod
    def _determine_theme(decayed: dict[str, float]) -> str:
        """Pick a theme from the dominant decayed-stat category.

        - High ``mob_kills`` -> retribution
        - High ``biomes_visited`` / ``distance_traveled`` -> discovery
        - High ``blocks_placed`` / ``blocks_broken`` -> invasion
        - Otherwise -> mystery (balanced / default)
        """
        combat_score = decayed.get("mob_kills", 0.0)
        explore_score = (
            decayed.get("biomes_visited", 0.0)
            + decayed.get("distance_traveled", 0.0) * 0.01
        )
        building_score = (
            decayed.get("blocks_placed", 0.0)
            + decayed.get("blocks_broken", 0.0)
        )

        scores: dict[str, float] = {
            "retribution": combat_score,
            "discovery": explore_score,
            "invasion": building_score,
        }

        max_theme = max(scores, key=lambda k: scores[k])
        max_val = scores[max_theme]

        # Require the dominant score to meaningfully exceed the others.
        others = [v for k, v in scores.items() if k != max_theme]
        if max_val < 1.0 or (others and max_val < 2 * max(others)):
            return "mystery"

        return max_theme

    # -- difficulty / scaling -----------------------------------------------

    @staticmethod
    def _compute_difficulty(intensity: float) -> int:
        """Map player intensity (0.0-1.0) to difficulty (1-10).

        Formula: ``base(3) + intensity * multiplier(7)`` clamped to [1, 10].
        More recent activity drives intensity higher, decayed activity lowers it.
        """
        raw = _BASE_DIFFICULTY + intensity * _DIFFICULTY_MULTIPLIER
        return max(1, min(10, round(raw)))

    @staticmethod
    def _compute_loot_quality(difficulty: int) -> float:
        """Inversely proportional to difficulty.  Range 0.5 - 2.0.

        Easy dungeons give better loot; hard dungeons are stingier.
        Linear interpolation: difficulty 1 -> 2.0, difficulty 10 -> 0.5.
        """
        quality = 2.0 - (difficulty - 1) * (1.5 / 9.0)
        return round(max(0.5, min(2.0, quality)), 2)

    @staticmethod
    def _compute_mob_multiplier(difficulty: int) -> float:
        """Proportional to difficulty.  Range 0.5 - 2.0.

        Easy dungeons have fewer mobs; hard dungeons swarm the player.
        Linear interpolation: difficulty 1 -> 0.5, difficulty 10 -> 2.0.
        """
        multiplier = 0.5 + (difficulty - 1) * (1.5 / 9.0)
        return round(max(0.5, min(2.0, multiplier)), 2)

    # -- story hooks --------------------------------------------------------

    def _generate_story_hook(
        self,
        player_uuid: str,
        player_name: str,
        theme: str,
    ) -> str:
        """Build a one-sentence story intro, optionally referencing past dungeons."""
        history = self._load_history(player_uuid)

        # If there is narrative history, prefer a continuity hook.
        if history:
            prev = history[-1]
            prev_dungeon = prev.get("dungeon_name", "the last dungeon")
            hook = random.choice(_CONTINUITY_HOOKS).format(
                prev_dungeon=prev_dungeon,
                player_name=player_name,
            )
            return hook

        # No history — pick a fresh hook for the theme.
        hooks = _STORY_HOOKS.get(theme, _STORY_HOOKS["mystery"])
        return random.choice(hooks).format(player_name=player_name)

    # -- narrative history persistence --------------------------------------

    def _history_path(self, player_uuid: str) -> Path:
        return self.data_dir / f"{player_uuid}_narrative_history.json"

    def _load_history(self, player_uuid: str) -> list[dict]:
        """Load the narrative history list for a player (empty list if none)."""
        path = self._history_path(player_uuid)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_history(self, player_uuid: str, history: list[dict]) -> None:
        path = self._history_path(player_uuid)
        path.write_text(json.dumps(history, indent=2))
