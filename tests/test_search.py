import threading
import time

import pytest

from app.scoring import Result
from app.search import AlreadyRunning, SearchManager
from app.store import Store
from app.worker import Scored, WorkerCrashed


class FakePool:
    workers = 4

    def run(self, fn, *args, timeout=None):
        return fn(*args)


class Scorer:
    """Scores rise with each call; optional gate pauses calls past a point."""

    def __init__(self, gate_after=None, reject=False, crash_on=None):
        self.calls = 0
        self.lock = threading.Lock()
        self.gate = threading.Event()
        self.gate_after = gate_after
        self.reject = reject
        self.crash_on = crash_on

    def __call__(self, seed):
        with self.lock:
            self.calls += 1
            n = self.calls
        if self.gate_after is not None and n > self.gate_after:
            self.gate.wait(10)
        if n == self.crash_on:
            raise WorkerCrashed("boom")
        reason = "Spawns in an ocean (ocean)" if self.reject else None
        result = Result(score=float(n), breakdown={}, mean_weirdness=0.0, rejected_reason=reason)
        return Scored(seed, result, (0, 0), "plains", [])


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "seeds.db"))


def wait(manager, seconds=10):
    end = time.time() + seconds
    while manager.status()["running"]:
        assert time.time() < end, "search did not finish"
        time.sleep(0.01)
    return manager.status()


def wait_for(condition, seconds=10):
    end = time.time() + seconds
    while not condition():
        assert time.time() < end, "condition never became true"
        time.sleep(0.01)


def test_search_saves_only_top_100_and_counts_all(store):
    m = SearchManager(FakePool(), store, scorer=Scorer())
    m.start(150)
    status = wait(m)
    rows = store.list("score")
    assert status["tried"] == 150 and status["target"] == 150 and not status["stopped_early"]
    assert len(rows) == 100 and min(r["score"] for r in rows) > 50 - 4
    assert status["best_score"] == rows[0]["score"] and status["best_seed"] == rows[0]["seed"]
    assert all(r["source"] == "search" for r in rows)


def test_second_search_is_rejected_while_running(store):
    scorer = Scorer(gate_after=0)
    m = SearchManager(FakePool(), store, scorer=scorer)
    m.start(10)
    with pytest.raises(AlreadyRunning):
        m.start(10)
    scorer.gate.set()
    wait(m)


def test_new_search_allowed_after_finish(store):
    m = SearchManager(FakePool(), store, scorer=Scorer())
    m.start(3)
    wait(m)
    m.start(2)
    assert wait(m)["tried"] == 2


def test_stop_ends_early_and_keeps_best_so_far(store):
    scorer = Scorer(gate_after=10)
    m = SearchManager(FakePool(), store, scorer=scorer)
    m.start(100000)
    wait_for(lambda: m.status()["tried"] >= 10)
    m.stop()
    scorer.gate.set()
    status = wait(m)
    assert status["stopped_early"] and status["tried"] < 100000
    assert store.list("score")


def test_saved_rows_exist_before_search_finishes(store):
    scorer = Scorer(gate_after=60)
    m = SearchManager(FakePool(), store, scorer=scorer)
    m.start(200)
    wait_for(lambda: len(store.list("score")) > 0)
    assert m.status()["running"]
    scorer.gate.set()
    wait(m)


def test_search_survives_one_crashed_seed(store):
    m = SearchManager(FakePool(), store, scorer=Scorer(crash_on=5))
    m.start(20)
    status = wait(m)
    assert status["tried"] == 20 and "boom" in status["error"]


def test_search_never_saves_rejected_seeds(store):
    m = SearchManager(FakePool(), store, scorer=Scorer(reject=True))
    m.start(20)
    status = wait(m)
    assert store.list("score") == [] and status["best_seed"] is None


def test_search_leaves_existing_manual_seed_alone(store):
    store.save(7, "mine", Result(1.0, {}, 0.0, None), (0, 0), "plains", [], "manual")
    m = SearchManager(FakePool(), store, scorer=Scorer())
    m.start(150)
    wait(m)
    assert store.get(7)["source"] == "manual"


def test_status_before_any_search(store):
    status = SearchManager(FakePool(), store, scorer=Scorer()).status()
    assert status["running"] is False and status["tried"] == 0 and status["target"] == 0
