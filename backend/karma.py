"""
Three-dimensional karma system for NemoCraft.

Tracks player morality across Violence, Nature, and Social dimensions.
Each dimension decays toward zero over time.  The composite score maps
to one of seven tiers that drive dungeon theming, palette, and mob selection.
"""

from __future__ import annotations

import math
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.config import settings


# ---------------------------------------------------------------------------
# Karma state model
# ---------------------------------------------------------------------------

class KarmaState(BaseModel):
    """Per-player karma dimensions and bookkeeping."""

    violence: float = Field(default=0.0, ge=-100, le=100)
    nature: float = Field(default=0.0, ge=-100, le=100)
    social: float = Field(default=0.0, ge=-100, le=100)
    last_updated: float = Field(default_factory=time.time)
    prev_counters: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Karma tiers
# ---------------------------------------------------------------------------

class KarmaTier(str, Enum):
    ABYSSAL = "abyssal"
    DARK = "dark"
    SHADOWED = "shadowed"
    NEUTRAL = "neutral"
    BLESSED = "blessed"
    SACRED = "sacred"
    CELESTIAL = "celestial"


def score_to_tier(score: float) -> KarmaTier:
    """Map a composite karma score to its tier."""
    if score <= -70:
        return KarmaTier.ABYSSAL
    elif score <= -30:
        return KarmaTier.DARK
    elif score <= -10:
        return KarmaTier.SHADOWED
    elif score < 10:
        return KarmaTier.NEUTRAL
    elif score < 30:
        return KarmaTier.BLESSED
    elif score < 70:
        return KarmaTier.SACRED
    else:
        return KarmaTier.CELESTIAL


# ---------------------------------------------------------------------------
# Action weights: stat field name -> (dimension, weight)
# ---------------------------------------------------------------------------

KARMA_ACTION_WEIGHTS: dict[str, tuple[str, float]] = {
    # Negative actions
    "killed_villager":       ("social",   -8),
    "killed_iron_golem":     ("social",   -5),
    "killed_cat":            ("social",   -4),
    "killed_wolf":           ("social",   -4),
    "killed_dolphin":        ("nature",   -4),
    "killed_horse":          ("violence", -3),
    "killed_donkey":         ("violence", -3),
    "killed_turtle":         ("nature",   -3),
    "killed_bee":            ("nature",   -3),
    "killed_cow":            ("violence", -2),
    "killed_pig":            ("violence", -2),
    "killed_sheep":          ("violence", -2),
    "killed_fox":            ("nature",   -2),
    "killed_chicken":        ("violence", -1),
    "killed_rabbit":         ("violence", -1),
    # Positive actions
    "raid_win":              ("social",   +10),
    "traded_with_villager":  ("social",   +3),
    "animals_bred":          ("nature",   +3),
    "pot_flower":            ("nature",   +2),
    "fish_caught":           ("nature",   +1),
    "talked_to_villager":    ("social",   +1),
    "bell_ring":             ("social",   +1),
}

# Bell rings are capped at 3 per snapshot cycle
_BELL_RING_CAP = 3


# ---------------------------------------------------------------------------
# Decay helper
# ---------------------------------------------------------------------------

def decay_toward_zero(value: float, hours_elapsed: float, decay_rate: float) -> float:
    """Exponentially decay *value* toward zero.

    Returns value * e^(-decay_rate * hours_elapsed), preserving sign.
    """
    if value == 0.0:
        return 0.0
    factor = math.exp(-decay_rate * hours_elapsed)
    return value * factor


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def compute_karma_deltas(
    current_counters: dict[str, int],
    prev_counters: dict[str, int],
) -> dict[str, float]:
    """Compute per-dimension karma deltas from counter differences.

    Returns ``{"violence": dv, "nature": dn, "social": ds}``.
    """
    deltas: dict[str, float] = {"violence": 0.0, "nature": 0.0, "social": 0.0}

    for stat_key, (dimension, weight) in KARMA_ACTION_WEIGHTS.items():
        current = current_counters.get(stat_key, 0)
        previous = prev_counters.get(stat_key, 0)
        diff = current - previous
        if diff <= 0:
            continue

        # Cap bell_ring increments
        if stat_key == "bell_ring":
            diff = min(diff, _BELL_RING_CAP)

        deltas[dimension] += diff * weight

    return deltas


# ---------------------------------------------------------------------------
# Main update function
# ---------------------------------------------------------------------------

def update_karma(
    state: KarmaState,
    current_counters: dict[str, int],
) -> KarmaState:
    """Apply decay + new deltas and return an updated KarmaState.

    1. Decay existing dimension values toward zero based on elapsed time.
    2. Compute deltas from counter differences.
    3. Add deltas and clamp each dimension to [-100, +100].
    """
    now = time.time()
    hours_elapsed = max(0.0, (now - state.last_updated) / 3600.0)
    decay_rate = settings.karma_decay_rate

    # Step 1: decay
    violence = decay_toward_zero(state.violence, hours_elapsed, decay_rate)
    nature = decay_toward_zero(state.nature, hours_elapsed, decay_rate)
    social = decay_toward_zero(state.social, hours_elapsed, decay_rate)

    # Step 2: compute deltas
    deltas = compute_karma_deltas(current_counters, state.prev_counters)

    # Step 3: apply and clamp
    violence = max(-100.0, min(100.0, violence + deltas["violence"]))
    nature = max(-100.0, min(100.0, nature + deltas["nature"]))
    social = max(-100.0, min(100.0, social + deltas["social"]))

    return KarmaState(
        violence=round(violence, 4),
        nature=round(nature, 4),
        social=round(social, 4),
        last_updated=now,
        prev_counters=dict(current_counters),
    )


def composite_score(state: KarmaState) -> float:
    """Compute the weighted composite karma score, clamped to [-100, +100]."""
    raw = (
        state.violence * settings.karma_violence_weight
        + state.nature * settings.karma_nature_weight
        + state.social * settings.karma_social_weight
    )
    return max(-100.0, min(100.0, round(raw, 2)))


# ---------------------------------------------------------------------------
# Per-tier theming data
# ---------------------------------------------------------------------------

TIER_THEMES: dict[KarmaTier, str] = {
    KarmaTier.ABYSSAL:   "void corruption",
    KarmaTier.DARK:      "punishment",
    KarmaTier.SHADOWED:  "deception",
    KarmaTier.NEUTRAL:   "mystery",
    KarmaTier.BLESSED:   "guardian trials",
    KarmaTier.SACRED:    "divine tests",
    KarmaTier.CELESTIAL: "ethereal ascension",
}

TIER_MOODS: dict[KarmaTier, str] = {
    KarmaTier.ABYSSAL:   "eldritch horror",
    KarmaTier.DARK:      "dark magic",
    KarmaTier.SHADOWED:  "moral ambiguity",
    KarmaTier.NEUTRAL:   "ancient",
    KarmaTier.BLESSED:   "hopeful",
    KarmaTier.SACRED:    "divine",
    KarmaTier.CELESTIAL: "ethereal",
}

TIER_PALETTES: dict[KarmaTier, str] = {
    KarmaTier.ABYSSAL:   "abyssal",
    KarmaTier.DARK:      "nether",
    KarmaTier.SHADOWED:  "deepslate",
    KarmaTier.NEUTRAL:   "stone",
    KarmaTier.BLESSED:   "sandstone",
    KarmaTier.SACRED:    "prismarine",
    KarmaTier.CELESTIAL: "end",
}

TIER_BLOCK_PALETTES: dict[KarmaTier, list[str]] = {
    KarmaTier.ABYSSAL: [
        "minecraft:crying_obsidian", "minecraft:sculk", "minecraft:black_concrete",
        "minecraft:obsidian", "minecraft:deepslate", "minecraft:sculk_vein",
    ],
    KarmaTier.DARK: [
        "minecraft:nether_bricks", "minecraft:blackstone", "minecraft:magma_block",
        "minecraft:polished_blackstone", "minecraft:soul_sand", "minecraft:red_nether_bricks",
    ],
    KarmaTier.SHADOWED: [
        "minecraft:deepslate", "minecraft:tuff", "minecraft:gray_concrete",
        "minecraft:cobbled_deepslate", "minecraft:deepslate_bricks", "minecraft:polished_deepslate",
    ],
    KarmaTier.NEUTRAL: [
        "minecraft:stone_bricks", "minecraft:cobblestone", "minecraft:mossy_stone_bricks",
        "minecraft:cracked_stone_bricks", "minecraft:smooth_stone",
    ],
    KarmaTier.BLESSED: [
        "minecraft:sandstone", "minecraft:smooth_sandstone", "minecraft:gold_block",
        "minecraft:chiseled_sandstone", "minecraft:cut_sandstone",
    ],
    KarmaTier.SACRED: [
        "minecraft:prismarine", "minecraft:quartz_block", "minecraft:sea_lantern",
        "minecraft:prismarine_bricks", "minecraft:dark_prismarine", "minecraft:quartz_pillar",
    ],
    KarmaTier.CELESTIAL: [
        "minecraft:purpur_block", "minecraft:end_stone", "minecraft:white_stained_glass",
        "minecraft:end_rod", "minecraft:purpur_pillar", "minecraft:end_stone_bricks",
    ],
}

TIER_MOB_PREFERENCES: dict[KarmaTier, list[str]] = {
    KarmaTier.ABYSSAL: [
        "minecraft:warden", "minecraft:wither_skeleton", "minecraft:phantom", "minecraft:evoker",
    ],
    KarmaTier.DARK: [
        "minecraft:blaze", "minecraft:piglin_brute", "minecraft:hoglin",
    ],
    KarmaTier.SHADOWED: [
        "minecraft:witch", "minecraft:spider", "minecraft:creeper", "minecraft:vex",
    ],
    KarmaTier.NEUTRAL: [
        "minecraft:zombie", "minecraft:skeleton",
    ],
    KarmaTier.BLESSED: [
        "minecraft:pillager", "minecraft:vindicator",
    ],
    KarmaTier.SACRED: [
        "minecraft:guardian", "minecraft:iron_golem",
    ],
    KarmaTier.CELESTIAL: [
        "minecraft:shulker", "minecraft:elder_guardian",
    ],
}

TIER_LOOT_MODIFIER: dict[KarmaTier, float] = {
    KarmaTier.ABYSSAL:   1.4,
    KarmaTier.DARK:      1.1,
    KarmaTier.SHADOWED:  1.0,
    KarmaTier.NEUTRAL:   1.0,
    KarmaTier.BLESSED:   1.0,
    KarmaTier.SACRED:    1.1,
    KarmaTier.CELESTIAL: 1.4,
}

TIER_STYLE_WEIGHTS: dict[KarmaTier, dict[str, float]] = {
    KarmaTier.ABYSSAL:   {"catacomb": 3, "ruins": 3, "arena": 1},
    KarmaTier.DARK:      {"fortress": 3, "arena": 2, "catacomb": 1},
    KarmaTier.SHADOWED:  {"catacomb": 2, "ruins": 2, "grand_hall": 1},
    KarmaTier.NEUTRAL:   {"grand_hall": 1, "arena": 1, "catacomb": 1, "cathedral": 1, "fortress": 1, "ruins": 1},
    KarmaTier.BLESSED:   {"grand_hall": 2, "fortress": 2, "cathedral": 1},
    KarmaTier.SACRED:    {"cathedral": 3, "grand_hall": 2, "fortress": 1},
    KarmaTier.CELESTIAL: {"cathedral": 3, "grand_hall": 3, "arena": 1},
}
