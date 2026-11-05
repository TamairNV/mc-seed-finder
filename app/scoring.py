"""Pure scoring of world facts. Every weight lives at the top of this file."""

from dataclasses import dataclass

import numpy as np

SPAWN_TOP = {"cherry_grove", "meadow", "mushroom_fields", "badlands", "eroded_badlands", "wooded_badlands"}
SPAWN_MIDDLE = {"plains", "savanna", "jungle", "birch_forest"}
SPAWN_POINTS = (20, 12, 5)

VARIETY_MAX = 15
VARIETY_LOW, VARIETY_HIGH = 30, 55

RARE_MAX = 25
RARE_WEIGHTS = {
    "mushroom_fields": 6, "cherry_grove": 4, "ice_spikes": 4, "eroded_badlands": 4, "pale_garden": 3,
    "badlands": 2, "bamboo_jungle": 2, "jagged_peaks": 2, "mangrove_swamp": 2, "old_growth_birch_forest": 2,
}

STRUCTURE_WEIGHTS = {
    "Village": 8, "Trial_Chambers": 6, "Mansion": 5, "Ancient_City": 4, "Monument": 3,
    "Desert_Pyramid": 1, "Jungle_Temple": 1, "Outpost": 1, "Trail_Ruins": 1,
}

TERRAIN_MAX = 10
TERRAIN_PEAK = 0.7
TERRAIN_FULL_SHARE = 0.15  # real seeds top out near 11%
VALLEY_LIMIT = -0.6

NEAR_BLOCKS = 2048

CAVE_BIOMES = {"dripstone_caves", "lush_caves", "deep_dark"}

SPRUCE_SPAWNS = {"taiga", "snowy_taiga", "old_growth_pine_taiga", "old_growth_spruce_taiga"}


@dataclass
class WorldFacts:
    spawn: tuple[int, int]
    spawn_biome: str
    biomes: np.ndarray
    cell_blocks: int
    origin_block: tuple[int, int]
    weirdness: np.ndarray
    structures: list[tuple[str, int, int]]


@dataclass
class Result:
    score: float
    breakdown: dict[str, float]
    mean_weirdness: float
    rejected_reason: str | None
    peak_share: float = 0.0


def _near(distance: float) -> float:
    return max(0.0, 1.0 - distance / NEAR_BLOCKS)


def _spawn_points(biome: str) -> int:
    top, middle, low = SPAWN_POINTS
    return top if biome in SPAWN_TOP else middle if biome in SPAWN_MIDDLE else low


def _variety_points(biomes: np.ndarray) -> float:
    share = (len(set(biomes.ravel().tolist()) - CAVE_BIOMES) - VARIETY_LOW) / (VARIETY_HIGH - VARIETY_LOW)
    return VARIETY_MAX * min(1.0, max(0.0, share))


def _rare_points(facts: WorldFacts) -> float:
    half = facts.cell_blocks / 2
    xs = facts.origin_block[0] + half + np.arange(facts.biomes.shape[1]) * facts.cell_blocks - facts.spawn[0]
    zs = facts.origin_block[1] + half + np.arange(facts.biomes.shape[0]) * facts.cell_blocks - facts.spawn[1]
    total = 0.0
    for name, weight in RARE_WEIGHTS.items():
        rows, cols = np.nonzero(facts.biomes == name)
        if rows.size:
            total += weight * _near(float(np.hypot(xs[cols], zs[rows]).min()))
    return min(RARE_MAX, total)


def _structure_points(facts: WorldFacts) -> float:
    nearest: dict[str, float] = {}
    for kind, x, z in facts.structures:
        d = float(np.hypot(x - facts.spawn[0], z - facts.spawn[1]))
        nearest[kind] = min(d, nearest.get(kind, d))
    return sum(STRUCTURE_WEIGHTS.get(kind, 0) * _near(d) for kind, d in nearest.items())


def _peaks_and_valleys(weirdness):
    return 1 - np.abs(3 * np.abs(weirdness) - 2)


def _peak_share(weirdness: np.ndarray) -> float:
    return float((_peaks_and_valleys(weirdness) >= TERRAIN_PEAK).mean())


def terrain_hint(weirdness: float) -> str:
    """What weirdness alone suggests. Height also depends on continentalness and erosion."""
    value = float(_peaks_and_valleys(weirdness))
    if value >= TERRAIN_PEAK:
        return "Peak-type terrain"
    if value <= VALLEY_LIMIT:
        return "Valley-type terrain"
    return "Mixed terrain"


def _rejection(biome: str) -> str | None:
    if biome in SPRUCE_SPAWNS:
        return f"Spawns in a spruce biome ({biome})"
    if "ocean" in biome:
        return f"Spawns in an ocean ({biome})"
    return None


def evaluate(facts: WorldFacts) -> Result:
    share = _peak_share(facts.weirdness)
    breakdown = {
        "spawn_biome": float(_spawn_points(facts.spawn_biome)),
        "variety": _variety_points(facts.biomes),
        "rare_biomes": _rare_points(facts),
        "structures": _structure_points(facts),
        "terrain": TERRAIN_MAX * min(1.0, share / TERRAIN_FULL_SHARE),
    }
    reason = _rejection(facts.spawn_biome)
    return Result(
        score=0.0 if reason else sum(breakdown.values()),
        breakdown=breakdown,
        mean_weirdness=float(facts.weirdness.mean()),
        rejected_reason=reason,
        peak_share=share,
    )
