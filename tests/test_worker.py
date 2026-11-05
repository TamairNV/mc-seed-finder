import os
import time

import pytest

from app.worker import Pool, WorkerCrashed, score_seed

SEED = 3874681947099440070


def scoring_rejects(biome):
    from app.scoring import rejection

    return rejection(biome) is not None


def test_worker_crash_is_contained_and_pool_recovers():
    pool = Pool(workers=1)
    with pytest.raises(WorkerCrashed):
        pool.run(os._exit, 1)
    assert pool.run(score_seed, SEED).seed == SEED


def test_timeout_is_reported_as_crash_and_pool_recovers():
    pool = Pool(workers=1)

    with pytest.raises(WorkerCrashed):
        pool.run(time.sleep, 30, timeout=0.5)
    assert pool.run(score_seed, SEED).seed == SEED


def test_score_seed_returns_real_world_facts():
    scored = score_seed(SEED)
    assert scored.spawn == (8, 8) and scored.spawn_biome == "meadow"
    assert scored.result.rejected_reason is None and 0 < scored.result.score <= 100
    assert scored.structures and all(len(s) == 3 for s in scored.structures)


def test_score_grid_reads_the_surface_not_caves(monkeypatch):
    from app import cubiomes, scoring, worker

    seen = {}
    real = scoring.evaluate

    def spy(facts):
        seen["biomes"] = facts.biomes
        return real(facts)

    monkeypatch.setattr(worker, "evaluate", spy)
    hilly = -7059255982915085877
    worker.score_seed(hilly)
    expected = worker._biome_names()[cubiomes.surface_grid(hilly, 16, -31, -31, 62, 62) & 255]
    assert (seen["biomes"] == expected).all()
    assert not set(seen["biomes"].ravel().tolist()) & scoring.CAVE_BIOMES


def test_point_reads_surface_cave_and_height():
    from app import worker

    hilly = -7059255982915085877
    spots = [worker.point(hilly, x, z) for x in range(-700, 700, 140) for z in range(-700, 700, 140)]
    assert all(s["biome"] not in {"dripstone_caves", "lush_caves", "deep_dark"} for s in spots)
    assert all(isinstance(s["height"], int) and -64 <= s["height"] <= 320 for s in spots)
    assert {s["cave_biome"] for s in spots} - {None} <= {"dripstone_caves", "lush_caves", "deep_dark"}
    assert any(s["cave_biome"] for s in spots) and any(s["cave_biome"] is None for s in spots)


def test_search_skips_the_scan_for_rejected_spawns(monkeypatch):
    from app import cubiomes, worker

    rejected = next(s for s in range(500) if scoring_rejects(cubiomes.biome_name(cubiomes.spawn(s)[2])))
    allowed = next(s for s in range(500) if not scoring_rejects(cubiomes.biome_name(cubiomes.spawn(s)[2])))

    def forbidden(*args):
        raise AssertionError("scanned the biomes of a rejected seed")

    assert worker.search_seed(allowed).seed == allowed
    monkeypatch.setattr(cubiomes, "surface_grid", forbidden)
    assert worker.search_seed(rejected) is None


def test_search_and_manual_scoring_agree():
    from app import worker

    assert worker.search_seed(SEED).result.score == worker.score_seed(SEED).result.score


def test_manual_scoring_still_explains_a_rejected_seed():
    from app import cubiomes, worker

    rejected = next(s for s in range(500) if scoring_rejects(cubiomes.biome_name(cubiomes.spawn(s)[2])))
    result = worker.score_seed(rejected).result
    assert result.rejected_reason and result.breakdown["variety"] >= 0


def test_score_covers_the_central_thousand_blocks():
    from app import worker

    assert worker.GRID_CELLS * worker.CELL_BLOCKS == 992


def test_pool_uses_eight_workers_by_default():
    assert Pool().workers == 8


def test_score_reports_biome_count():
    assert 1 <= score_seed(SEED).result.biome_count <= 60


def test_structures_cover_the_wider_map():
    assert any(max(abs(x), abs(z)) >= 2048 for _, x, z in score_seed(SEED).structures)


def test_score_only_counts_structures_near_spawn():
    from app import worker

    scored = score_seed(SEED)
    assert scored.result.breakdown["structures"] <= 30 and worker.point(SEED, 8, 8)["terrain"]
