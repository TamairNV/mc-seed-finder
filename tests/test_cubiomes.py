from app import cubiomes

SEED = 3874681947099440070  # spawned in meadow during the feasibility test
KNOWN_KINDS = {"Village", "Mansion", "Monument", "Outpost", "Desert_Pyramid", "Jungle_Temple",
               "Ancient_City", "Trial_Chambers", "Trail_Ruins"}


def test_same_seed_gives_identical_results():
    assert cubiomes.spawn(SEED) == cubiomes.spawn(SEED)
    assert (cubiomes.biome_grid(SEED, 16, -128, -128, 32, 32, 4)
            == cubiomes.biome_grid(SEED, 16, -128, -128, 32, 32, 4)).all()


def test_spawn_matches_feasibility_result():
    x, z, biome = cubiomes.spawn(SEED)
    assert (x, z) == (8, 8) and cubiomes.biome_name(biome) == "meadow"


def test_biome_grid_axes_and_scale_match_direct_call():
    grid = cubiomes.biome_grid(SEED, 4, -512, -512, 64, 32, 15)
    assert grid.shape == (32, 64)
    assert grid[7, 50] == cubiomes.biome_at(SEED, 4, -512 + 50, -512 + 7, 15)


def test_weirdness_grid_axes_and_step_match_direct_call():
    grid = cubiomes.weirdness_grid(SEED, -512, -512, 64, 32, 4)
    assert grid.shape == (32, 64)
    assert grid[7, 50] == cubiomes.weirdness_at(SEED, -512 + 50 * 4, -512 + 7 * 4)


def test_structures_are_in_range_and_known_kinds():
    found = cubiomes.structures(SEED)
    assert found and all(abs(s.x) < 2048 and abs(s.z) < 2048 for s in found)
    assert {s.kind for s in found} <= KNOWN_KINDS


def test_negative_seed_is_accepted():
    assert cubiomes.spawn(-1) == cubiomes.spawn(-1)


def test_biome_colors_shape():
    assert cubiomes.biome_colors().shape == (256, 3)


CAVE_BIOMES = {"dripstone_caves", "lush_caves", "deep_dark"}


def test_spawn_biome_is_read_at_the_surface_not_underground():
    # Read as dripstone_caves when sampled at a fixed block height of 60.
    assert cubiomes.biome_name(cubiomes.spawn(4728016566880465652)[2]) == "meadow"


def test_spawn_biome_is_never_a_cave_across_many_seeds():
    names = {cubiomes.biome_name(cubiomes.spawn(seed)[2]) for seed in range(300)}
    assert not names & CAVE_BIOMES
