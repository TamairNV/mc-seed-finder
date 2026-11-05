import pytest

from app.scoring import Result
from app.store import Store

SEED = 42
result = Result(score=50.0, breakdown={"terrain": 5.0}, mean_weirdness=0.1, rejected_reason=None)


@pytest.fixture
def s(tmp_path):
    return Store(str(tmp_path / "seeds.db"))


def save(store, seed, score=50.0, weird=0.1, reason=None, source="search"):
    r = Result(score=score, breakdown={}, mean_weirdness=weird, rejected_reason=reason)
    store.save(seed, None, r, (0, 0), "plains", [], source)


def test_save_and_get_round_trip(s):
    s.save(SEED, "text", result, (8, -8), "meadow", [("Village", 1, 2)], "manual")
    row = s.get(SEED)
    assert row["seed"] == "42" and row["input_text"] == "text" and row["score"] == 50.0
    assert row["breakdown"] == {"terrain": 5.0} and row["structures"] == [["Village", 1, 2]]
    assert (row["spawn_x"], row["spawn_z"], row["spawn_biome"]) == (8, -8, "meadow")
    assert row["mean_weirdness"] == 0.1 and row["rejected_reason"] is None
    assert row["source"] == "manual" and row["created_at"]


def test_get_missing_is_none(s):
    assert s.get(1) is None


def test_sort_orders_highest_first(s):
    save(s, 1, score=10, weird=0.9)
    save(s, 2, score=90, weird=0.1)
    save(s, 3, score=0, weird=0.5, reason="Spawns in a spruce biome (taiga)")
    assert [r["seed"] for r in s.list("score")] == ["2", "1", "3"]
    assert [r["seed"] for r in s.list("weirdness")] == ["1", "3", "2"]


def test_rejected_sort_last_even_with_equal_score(s):
    save(s, 1, score=0, reason="no")
    save(s, 2, score=0)
    assert [r["seed"] for r in s.list("score")] == ["2", "1"]


def test_seed_stays_exact(s):
    save(s, 9007199254740993)
    assert s.get(9007199254740993)["seed"] == "9007199254740993"


def test_negative_seed(s):
    save(s, -9223372036854775808)
    assert s.get(-9223372036854775808)["seed"] == "-9223372036854775808"


def test_resaving_updates_one_row_and_manual_wins(s):
    s.save(SEED, None, result, (0, 0), "plains", [], "search")
    s.save(SEED, "my seed", result, (0, 0), "plains", [], "manual")
    s.save(SEED, None, result, (0, 0), "plains", [], "search")
    row = s.get(SEED)
    assert row["source"] == "manual" and row["input_text"] == "my seed"
    assert len(s.list("score")) == 1


def test_delete_search_seed_never_touches_manual(s):
    save(s, 1, source="search")
    save(s, 2, source="manual")
    s.delete_search_seed(1)
    s.delete_search_seed(2)
    assert s.get(1) is None and s.get(2) is not None


def test_manual_seeds_stay_listed_after_many_search_seeds(s):
    save(s, 1, score=0, reason="Spawns in an ocean (ocean)", source="manual")
    for seed in range(100, 700):
        save(s, seed, score=50)
    rows = s.list("score")
    assert "1" in {r["seed"] for r in rows}
    assert len(rows) == 501  # the newest 500 search rows plus the manual one
    assert rows[-1]["seed"] == "1"
