import numpy as np
import pytest

from app.scoring import WorldFacts, evaluate

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
    assert b["spawn_biome"] == 20 and b["variety"] == 15
    assert b["rare_biomes"] == pytest.approx(25)
    assert b["structures"] == pytest.approx(30)
    assert b["terrain"] == 10
    assert result.score == pytest.approx(100)


@pytest.mark.parametrize("biome,points", [("cherry_grove", 20), ("plains", 12), ("forest", 5)])
def test_spawn_biome_tiers(biome, points):
    assert evaluate(facts(spawn_biome=biome)).breakdown["spawn_biome"] == points


def test_closer_structure_scores_more():
    near = evaluate(facts(structures=[("Village", 100, 0)])).breakdown["structures"]
    far = evaluate(facts(structures=[("Village", 1500, 0)])).breakdown["structures"]
    assert near > far > 0


def test_structure_distance_is_from_spawn_not_origin():
    near = evaluate(facts(spawn=(1000, 0), structures=[("Village", 1000, 0)])).breakdown["structures"]
    assert near == pytest.approx(8)


def test_many_villages_do_not_exceed_cap():
    one = evaluate(facts(structures=[("Village", 100, 0)])).breakdown["structures"]
    many = evaluate(facts(structures=[("Village", 100, 0)] * 50)).breakdown["structures"]
    assert many == one


def test_closer_rare_biome_scores_more():
    near = evaluate(facts(biomes=biomes_with("mushroom_fields", 33, 33))).breakdown["rare_biomes"]
    far = evaluate(facts(biomes=biomes_with("mushroom_fields", 0, 0))).breakdown["rare_biomes"]
    assert near > far > 0


def test_variety_scale():
    assert evaluate(facts()).breakdown["variety"] == 0


def test_terrain_uses_peaks_formula():
    peaks = evaluate(facts(weirdness=np.full((64, 64), 2 / 3))).breakdown["terrain"]
    valleys = evaluate(facts(weirdness=np.zeros((64, 64)))).breakdown["terrain"]
    assert peaks == 10 and valleys == 0


def test_mean_weirdness_not_in_score():
    pos = evaluate(facts(weirdness=np.full((64, 64), 2 / 3)))
    neg = evaluate(facts(weirdness=np.full((64, 64), -2 / 3)))
    assert pos.score == neg.score and pos.mean_weirdness > 0 > neg.mean_weirdness
