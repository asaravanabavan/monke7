"""Evolving narrative engine that generates story context based on player behavior.

Determines dungeon theme, difficulty, mood, loot quality, and mob density from
a player's decayed stats and play-style. Maintains per-player narrative history
so that successive dungeons feel like a continuous story arc.

When the karma system is enabled, karma tier overrides the playstyle-based
theme/mood/palette for non-neutral players.
"""

import json
import random
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.stats import PlayerProfile
from backend.karma import (
    KarmaTier,
    TIER_THEMES,
    TIER_MOODS,
    TIER_PALETTES,
    TIER_LOOT_MODIFIER,
)


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
        ..., ge=0.5, le=3.0,
        description="Loot quality multiplier (0.5-3.0)",
    )
    mob_count_multiplier: float = Field(
        ..., ge=0.5, le=2.0,
        description="Mob count multiplier (0.5-2.0)",
    )
    active_quest_names: list[str] = Field(
        default_factory=list,
        description="Names of player's currently active quests for story continuity",
    )
    active_quest_destinations: list[str] = Field(
        default_factory=list,
        description="Destination types from active quests (dungeon, village, etc.)",
    )
    # Karma-related context (all optional for backward compatibility)
    karma_score: float = Field(default=0.0, description="Composite karma score")
    karma_tier: str = Field(default="neutral", description="Karma tier name")
    karma_theme: str = Field(default="", description="Karma-driven theme override")
    karma_mood: str = Field(default="", description="Karma-driven mood override")
    karma_palette: str = Field(default="", description="Karma-driven palette override")
    karma_narrative: str = Field(default="", description="Karma flavor text for AI")


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
# Karma story hooks — 5 per tier
# ---------------------------------------------------------------------------

_KARMA_STORY_HOOKS: dict[str, list[str]] = {
    "abyssal": [
        "The void itself has taken notice of {player_name}'s cruelty, splitting the earth to reveal an abyssal maw.",
        "Reality warps around {player_name} as the consequences of unspeakable acts manifest in stone and shadow.",
        "An eldritch corruption seeps from the ground where {player_name} walks, forming a twisted labyrinth.",
        "The screams of {player_name}'s countless victims have coalesced into something sentient and hungry.",
        "Beneath {player_name}'s feet, the world rots — a dungeon born of pure malice claws its way to the surface.",
    ],
    "dark": [
        "Dark forces have gathered to punish {player_name} for a trail of destruction left behind.",
        "The netherworld stirs — {player_name}'s violent path has drawn the attention of dark powers.",
        "A fortress of punishment rises from the earth, built by the rage of those {player_name} has wronged.",
        "Shadows whisper {player_name}'s misdeeds, and the darkness answers with a trial of fire and pain.",
        "The land itself curses {player_name}, spawning a dungeon of dark retribution.",
    ],
    "shadowed": [
        "Moral ambiguity follows {player_name} like a shadow, and the shadows now take form.",
        "Neither fully innocent nor guilty, {player_name} draws a dungeon of tests and deception.",
        "The world watches {player_name} with suspicion — these halls will reveal true intentions.",
        "A dungeon of mirrors and illusions appears, reflecting {player_name}'s uncertain nature.",
        "The grey path {player_name} walks has led to a place where nothing is as it seems.",
    ],
    "blessed": [
        "The virtuous deeds of {player_name} have earned the attention of guardian spirits.",
        "{player_name}'s kindness has not gone unnoticed — a trial of worthiness awaits.",
        "Golden light marks the entrance to a dungeon of trials, drawn by {player_name}'s good heart.",
        "The protectors of the realm test {player_name}'s resolve in a dungeon of honor.",
        "Hope blooms where {player_name} treads — but hope must be defended in these hallowed halls.",
    ],
    "sacred": [
        "A holy temple has risen, drawn by {player_name}'s devotion to protecting the innocent.",
        "Divine forces have prepared a sacred trial for {player_name}, worthy champion of the people.",
        "Prismarine towers shimmer into existence — {player_name}'s virtue has awakened an ancient sanctum.",
        "The gods themselves have taken notice of {player_name}'s compassion and offer a divine challenge.",
        "Sacred waters flow around a temple born from {player_name}'s unwavering goodness.",
    ],
    "celestial": [
        "The heavens part for {player_name}, revealing an ethereal realm beyond mortal comprehension.",
        "{player_name}'s purity of heart has opened a gateway to a celestial dungeon among the stars.",
        "End crystals resonate with {player_name}'s virtue, lifting a dungeon of ascension into being.",
        "Angels whisper of {player_name}'s legendary kindness as celestial halls materialize from light.",
        "The final test of transcendence awaits {player_name} in a palace woven from starlight and hope.",
    ],
}

_KARMA_SHIFT_MESSAGES: dict[str, str] = {
    "darkening": "A shadow falls across the land as {player_name}'s karma darkens...",
    "lightening": "The air brightens as {player_name}'s karma grows more virtuous...",
}


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
        6. Include active quest context for story continuity.
        7. If karma is non-neutral, override theme/mood/palette with karma tier data.
        """
        profile = PlayerProfile(player_uuid, data_dir=str(self.data_dir))
        decayed = profile.get_decayed_stats()
        intensity = profile.get_intensity()

        theme = self._determine_theme(decayed)
        mood = _THEME_MOODS.get(theme, "ancient")
        difficulty = self._compute_difficulty(intensity)
        loot_quality = self._compute_loot_quality(difficulty)
        mob_multiplier = self._compute_mob_multiplier(difficulty)

        # Karma integration
        karma_score = profile.get_karma_score()
        karma_tier = profile.get_karma_tier()
        karma_theme = ""
        karma_mood = ""
        karma_palette = ""
        karma_narrative = ""

        if settings.karma_enable and karma_tier != KarmaTier.NEUTRAL:
            # Karma overrides theme and mood for non-neutral players
            karma_theme = TIER_THEMES[karma_tier]
            karma_mood = TIER_MOODS[karma_tier]
            karma_palette = TIER_PALETTES[karma_tier]
            theme = karma_theme
            mood = karma_mood

            # Apply karma loot modifier (extreme alignments get better loot)
            loot_modifier = TIER_LOOT_MODIFIER[karma_tier]
            loot_quality = round(min(3.0, max(0.5, loot_quality * loot_modifier)), 2)

            # Build karma narrative flavor text
            karma_narrative = self._build_karma_narrative(
                karma_tier, karma_score, player_name,
            )

        # Generate story hook (karma-aware)
        story_hook = self._generate_story_hook(
            player_uuid, player_name, theme, karma_tier,
        )

        # Load active quest context for narrative continuity
        quest_names, quest_destinations = self._load_active_quest_context(player_uuid)

        return NarrativeContext(
            theme=theme,
            mood=mood,
            difficulty_level=difficulty,
            story_hook=story_hook,
            loot_quality=loot_quality,
            mob_count_multiplier=mob_multiplier,
            active_quest_names=quest_names,
            active_quest_destinations=quest_destinations,
            karma_score=karma_score,
            karma_tier=karma_tier.value,
            karma_theme=karma_theme,
            karma_mood=karma_mood,
            karma_palette=karma_palette,
            karma_narrative=karma_narrative,
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
        karma_tier: KarmaTier = KarmaTier.NEUTRAL,
    ) -> str:
        """Build a one-sentence story intro, optionally referencing past dungeons.

        When karma is non-neutral, prefers karma-tier-specific hooks.
        """
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

        # Karma-tier-specific hooks for non-neutral karma
        if karma_tier != KarmaTier.NEUTRAL and karma_tier.value in _KARMA_STORY_HOOKS:
            hooks = _KARMA_STORY_HOOKS[karma_tier.value]
            return random.choice(hooks).format(player_name=player_name)

        # No history, neutral karma — pick a fresh hook for the theme.
        hooks = _STORY_HOOKS.get(theme, _STORY_HOOKS["mystery"])
        return random.choice(hooks).format(player_name=player_name)

    @staticmethod
    def _build_karma_narrative(
        karma_tier: KarmaTier,
        karma_score: float,
        player_name: str,
    ) -> str:
        """Generate descriptive flavor text about the player's karma for AI context."""
        tier_name = karma_tier.value.title()
        alignment = "dark" if karma_score < 0 else "virtuous"
        intensity = "extreme" if abs(karma_score) >= 70 else (
            "strong" if abs(karma_score) >= 30 else "mild"
        )
        return (
            f"{player_name} has {intensity} {alignment} karma (score: {karma_score:.0f}, "
            f"tier: {tier_name}). The dungeon should reflect this moral alignment "
            f"through its architecture, atmosphere, block palette, and mob selection."
        )

    # -- quest context integration -----------------------------------------

    def _load_active_quest_context(
        self,
        player_uuid: str,
    ) -> tuple[list[str], list[str]]:
        """Load active quest names and destinations for narrative continuity.

        Returns (quest_names, quest_destinations) from the player's quest log.
        Fails silently if the quest module isn't available or has no data.
        """
        try:
            quest_path = self.data_dir / f"{player_uuid}_quests.json"
            if quest_path.exists():
                data = json.loads(quest_path.read_text())
                active = data.get("active_quests", [])
                names = [q.get("name", "") for q in active if q.get("status") in ("available", "active")]
                destinations = [q.get("destination_type", "") for q in active if q.get("status") in ("available", "active")]
                return names, destinations
        except (json.JSONDecodeError, OSError):
            pass
        return [], []

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
