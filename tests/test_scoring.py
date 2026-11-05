import numpy as np
import pytest

from app import scoring
from app.scoring import WorldFacts, evaluate, terrain_hint

RARE = ["mushroom_fields", "cherry_grove", "ice_spikes", "eroded_badlands", "pale_garden", "badlands",
        "bamboo_jungle", "jagged_peaks", "mangrove_swamp", "old_growth_birch_forest"]
KINDS = ["Village", "Trial_Chambers", "Mansion", "Ancient_City", "Monument", "Desert_Pyramid",
         "Jungle_Temple", "Outpost", "Trail_Ruins"]


def facts(**overrides):
    base = dict(
        spawn=(0, 0), spawn_biome="plains",
        biomes=np.full((64, 64), "plains", dtype=object),
        cell_blocks=16, origin_block=(-512, -512),
        weirdness=np.zeros((64, 64)), structures=[],
    )
    return WorldFacts(**{**base, **overrides})


def biomes_with(name, row, col):
    grid = np.full((64, 64), "plains", dtype=object)
    grid[row, col] = name
    return grid


def richest_possible_facts():
    names = [f"biome_{i}" for i in range(60)]
    grid = np.array((names * 69)[:64 * 64], dtype=object).reshape(64, 64)
    for i, name in enumerate(RARE):
        grid[31 + i % 3, 31 + i // 3] = name
    return facts(
        spawn_biome="cherry_grove", biomes=grid,
        weirdness=np.full((64, 64), 2 / 3),
        structures=[(k, 0, 0) for k in KINDS],
    )


@pytest.mark.parametrize("biome", ["taiga", "snowy_taiga", "old_growth_pine_taiga",
                                   "old_growth_spruce_taiga", "ocean", "deep_cold_ocean"])
def test_bad_spawn_rejected(biome):
    r = evaluate(facts(spawn_biome=biome))
    assert r.score == 0 and r.rejected_reason and r.breakdown


def test_good_spawn_not_rejected():
    assert evaluate(facts()).rejected_reason is None


def test_component_maximums():
    result = evaluate(richest_possible_facts())
    b = result.breakdown
    assert b["spawn_biome"] == 5 and b["variety"] == 40
    assert b["rare_biomes"] == pytest.approx(25)
    assert b["structures"] == pytest.approx(20)
    assert b["terrain"] == 10
    assert result.score == pytest.approx(100)


@pytest.mark.parametrize("biome,points", [("cherry_grove", 5), ("plains", 3), ("forest", 1)])
def test_spawn_biome_tiers(biome, points):
    assert evaluate(facts(spawn_biome=biome)).breakdown["spawn_biome"] == points


def test_closer_structure_scores_more():
    near = evaluate(facts(structures=[("Village", 100, 0)])).breakdown["structures"]
    far = evaluate(facts(structures=[("Village", 1500, 0)])).breakdown["structures"]
    assert near > far > 0


def test_structure_distance_is_from_spawn_not_origin():
    near = evaluate(facts(spawn=(1000, 0), structures=[("Village", 1000, 0)])).breakdown["structures"]
    assert near == pytest.approx(6)


def test_many_villages_do_not_exceed_cap():
    one = evaluate(facts(structures=[("Village", 100, 0)])).breakdown["structures"]
    many = evaluate(facts(structures=[("Village", 100, 0)] * 50)).breakdown["structures"]
    assert many == one


def test_closer_rare_biome_scores_more():
    near = evaluate(facts(biomes=biomes_with("mushroom_fields", 33, 33))).breakdown["rare_biomes"]
    far = evaluate(facts(biomes=biomes_with("mushroom_fields", 0, 0))).breakdown["rare_biomes"]
    assert near > far > 0


def test_one_biome_scores_no_variety():
    assert evaluate(facts()).breakdown["variety"] == 0


def mixed_grid(counts):
    """A 64x64 grid holding each named biome the given number of times, with plains filling the rest."""
    cells = [name for name, count in counts.items() for _ in range(count)]
    cells += ["plains"] * (64 * 64 - len(cells))
    return np.array(cells, dtype=object).reshape(64, 64)


def test_even_mix_beats_the_same_biomes_as_tiny_patches():
    names = [f"biome_{i}" for i in range(14)]
    even = mixed_grid({name: 64 * 64 // 15 for name in names})
    patchy = mixed_grid({name: 1 for name in names})
    assert evaluate(facts(biomes=even)).biome_count == evaluate(facts(biomes=patchy)).biome_count == 15
    assert evaluate(facts(biomes=even)).breakdown["variety"] > evaluate(facts(biomes=patchy)).breakdown["variety"] + 10


def test_more_biomes_score_more_even_when_equally_mixed():
    few = mixed_grid({f"biome_{i}": 64 * 64 // 8 for i in range(7)})
    many = mixed_grid({f"biome_{i}": 64 * 64 // 16 for i in range(15)})
    assert evaluate(facts(biomes=many)).breakdown["variety"] > evaluate(facts(biomes=few)).breakdown["variety"]


def test_variety_outweighs_every_other_part():
    assert scoring.VARIETY_MAX > scoring.RARE_MAX
    assert scoring.VARIETY_MAX > sum(scoring.STRUCTURE_WEIGHTS.values())
    assert scoring.VARIETY_MAX > max(scoring.SPAWN_POINTS) + scoring.TERRAIN_MAX


def test_rare_biome_far_from_spawn_is_worth_little():
    grid = biomes_with("mushroom_fields", 0, 0)  # about 713 blocks from a spawn at 0,0
    assert evaluate(facts(biomes=grid)).breakdown["rare_biomes"] == pytest.approx(12 * (1 - 712.8 / 1000), abs=0.05)


def test_biome_count_leaves_out_caves():
    assert evaluate(facts(biomes=biomes_with("deep_dark", 0, 0))).biome_count == 1


def test_terrain_uses_peaks_formula():
    peaks = evaluate(facts(weirdness=np.full((64, 64), 2 / 3))).breakdown["terrain"]
    valleys = evaluate(facts(weirdness=np.zeros((64, 64)))).breakdown["terrain"]
    assert peaks == 10 and valleys == 0


def test_mean_weirdness_not_in_score():
    pos = evaluate(facts(weirdness=np.full((64, 64), 2 / 3)))
    neg = evaluate(facts(weirdness=np.full((64, 64), -2 / 3)))
    assert pos.score == neg.score and pos.mean_weirdness > 0 > neg.mean_weirdness


def test_cave_biomes_do_not_count_towards_variety():
    names = [f"biome_{i}" for i in range(40)]
    plain = np.array((names * 103)[:64 * 64], dtype=object).reshape(64, 64)
    caves = plain.copy()
    caves[0, :3] = ["dripstone_caves", "lush_caves", "deep_dark"]
    assert evaluate(facts(biomes=caves)).breakdown["variety"] == evaluate(facts(biomes=plain)).breakdown["variety"]


def test_peak_share_is_reported():
    assert evaluate(facts(weirdness=np.full((64, 64), 2 / 3))).peak_share == 1.0
    assert evaluate(facts(weirdness=np.zeros((64, 64)))).peak_share == 0.0


def test_terrain_scale_fits_real_seeds():
    grid = np.zeros((64, 64))
    grid[:, :5] = 2 / 3  # 5/64 is about 7.8% of the map
    assert evaluate(facts(weirdness=grid)).breakdown["terrain"] == pytest.approx(
        min(10, 10 * (5 / 64) / scoring.TERRAIN_FULL_SHARE))


@pytest.mark.parametrize("weirdness,word", [
    (2 / 3, "Peak"), (-2 / 3, "Peak"), (0.0, "Valley"), (0.05, "Valley"), (1.0, "Mixed"), (0.33, "Mixed"),
])
def test_terrain_hint(weirdness, word):
    assert terrain_hint(weirdness).startswith(word)
