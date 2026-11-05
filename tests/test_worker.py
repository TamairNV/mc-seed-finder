import os
import time

import pytest

from app.worker import Pool, WorkerCrashed, score_seed

SEED = 3874681947099440070


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


def test_score_grid_uses_the_same_height_as_the_map(monkeypatch):
    from app import cubiomes, render, worker

    real = cubiomes.biome_grid
    heights = []

    def spy(seed, scale, x, z, w, h, y):
        heights.append(y)
        return real(seed, scale, x, z, w, h, y)

    monkeypatch.setattr(cubiomes, "biome_grid", spy)
    worker.score_seed(SEED)
    assert heights == [render.MAP_Y_4]


def test_structures_cover_the_wider_map():
    assert any(max(abs(x), abs(z)) >= 2048 for _, x, z in score_seed(SEED).structures)


def test_score_only_counts_structures_near_spawn():
    from app import worker

    scored = score_seed(SEED)
    assert scored.result.breakdown["structures"] <= 30 and worker.point(SEED, 8, 8)["terrain"]
