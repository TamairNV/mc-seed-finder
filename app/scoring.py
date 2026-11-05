"""Pure scoring of world facts. Every weight lives at the top of this file."""

from dataclasses import dataclass

import numpy as np

SPAWN_TOP = {"cherry_grove", "meadow", "mushroom_fields", "badlands", "eroded_badlands", "wooded_badlands"}
SPAWN_MIDDLE = {"plains", "savanna", "jungle", "birch_forest"}
SPAWN_POINTS = (5, 3, 1)

# Half for how many biomes there are, half for how evenly they're mixed. The ranges come from
# 1,200 random seeds at this area and detail, running from a dull seed to about the best seen.
VARIETY_MAX = 40
BIOME_COUNT_LOW, BIOME_COUNT_HIGH = 7, 22
BIOME_MIX_LOW, BIOME_MIX_HIGH = 3.5, 12.0

RARE_MAX = 25
RARE_WEIGHTS = {
    "mushroom_fields": 12, "cherry_grove": 8, "ice_spikes": 8, "eroded_badlands": 8, "pale_garden": 6,
    "badlands": 4, "bamboo_jungle": 4, "jagged_peaks": 4, "mangrove_swamp": 4, "old_growth_birch_forest": 4,
}

STRUCTURE_WEIGHTS = {
    "Village": 6, "Trial_Chambers": 4, "Mansion": 3, "Ancient_City": 3, "Monument": 2,
    "Desert_Pyramid": 0.5, "Jungle_Temple": 0.5, "Outpost": 0.5, "Trail_Ruins": 0.5,
}

TERRAIN_MAX = 10
TERRAIN_PEAK = 0.7
TERRAIN_FULL_SHARE = 0.15  # real seeds top out near 11%
VALLEY_LIMIT = -0.6

STRUCTURE_NEAR_BLOCKS = 2048
RARE_NEAR_BLOCKS = 1000

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
    biome_count: int = 0


def _near(distance: float, limit: int) -> float:
    return max(0.0, 1.0 - distance / limit)


def _spawn_points(biome: str) -> int:
    top, middle, low = SPAWN_POINTS
    return top if biome in SPAWN_TOP else middle if biome in SPAWN_MIDDLE else low


def _surface_counts(biomes: np.ndarray) -> np.ndarray:
    names, counts = np.unique(biomes, return_counts=True)
    return counts[[name not in CAVE_BIOMES for name in names]]


def _scale(value: float, low: float, high: float) -> float:
    return min(1.0, max(0.0, (value - low) / (high - low)))


def _variety_points(counts: np.ndarray) -> float:
    """The mix is the number of equally common biomes with the same spread, so tiny patches add little."""
    shares = counts / counts.sum()
    mix = float(np.exp(-(shares * np.log(shares)).sum()))
    return VARIETY_MAX / 2 * (_scale(counts.size, BIOME_COUNT_LOW, BIOME_COUNT_HIGH)
                              + _scale(mix, BIOME_MIX_LOW, BIOME_MIX_HIGH))


def _rare_points(facts: WorldFacts) -> float:
    half = facts.cell_blocks / 2
    xs = facts.origin_block[0] + half + np.arange(facts.biomes.shape[1]) * facts.cell_blocks - facts.spawn[0]
    zs = facts.origin_block[1] + half + np.arange(facts.biomes.shape[0]) * facts.cell_blocks - facts.spawn[1]
    total = 0.0
    for name, weight in RARE_WEIGHTS.items():
        rows, cols = np.nonzero(facts.biomes == name)
        if rows.size:
            total += weight * _near(float(np.hypot(xs[cols], zs[rows]).min()), RARE_NEAR_BLOCKS)
    return min(RARE_MAX, total)


def _structure_points(facts: WorldFacts) -> float:
    nearest: dict[str, float] = {}
    for kind, x, z in facts.structures:
        d = float(np.hypot(x - facts.spawn[0], z - facts.spawn[1]))
        nearest[kind] = min(d, nearest.get(kind, d))
    return sum(STRUCTURE_WEIGHTS.get(kind, 0) * _near(d, STRUCTURE_NEAR_BLOCKS) for kind, d in nearest.items())


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


def rejection(biome: str) -> str | None:
    if biome in SPRUCE_SPAWNS:
        return f"Spawns in a spruce biome ({biome})"
    if "ocean" in biome:
        return f"Spawns in an ocean ({biome})"
    return None


def evaluate(facts: WorldFacts) -> Result:
    share = _peak_share(facts.weirdness)
    counts = _surface_counts(facts.biomes)
    breakdown = {
        "spawn_biome": float(_spawn_points(facts.spawn_biome)),
        "variety": _variety_points(counts),
        "rare_biomes": _rare_points(facts),
        "structures": _structure_points(facts),
        "terrain": TERRAIN_MAX * min(1.0, share / TERRAIN_FULL_SHARE),
    }
    reason = rejection(facts.spawn_biome)
    return Result(
        score=0.0 if reason else sum(breakdown.values()),
        breakdown=breakdown,
        mean_weirdness=float(facts.weirdness.mean()),
        rejected_reason=reason,
        peak_share=share,
        biome_count=int(counts.size),
    )
