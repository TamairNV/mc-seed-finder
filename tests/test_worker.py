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
