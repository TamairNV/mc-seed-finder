import pytest

from app.scoring import Result
from app.store import Store

SEED = 42
result = Result(score=50.0, breakdown={"terrain": 5.0}, mean_weirdness=0.1, rejected_reason=None)


@pytest.fixture
def s(tmp_path):
    return Store(str(tmp_path / "seeds.db"))


def save(store, seed, score=50.0, peak=0.1, reason=None, source="search"):
    r = Result(score=score, breakdown={}, mean_weirdness=0.0, rejected_reason=reason, peak_share=peak)
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
    save(s, 1, score=10, peak=0.9)
    save(s, 2, score=90, peak=0.1)
    save(s, 3, score=0, peak=0.5, reason="Spawns in a spruce biome (taiga)")
    assert [r["seed"] for r in s.list("score")] == ["2", "1", "3"]
    assert [r["seed"] for r in s.list("peak")] == ["1", "2", "3"]


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


def test_shortlist_round_trip_and_filter(s):
    save(s, 1)
    save(s, 2)
    assert s.get(1)["shortlisted"] is False
    assert s.set_shortlisted(1, True) is True
    assert s.get(1)["shortlisted"] is True
    assert [r["seed"] for r in s.list("score", shortlisted_only=True)] == ["1"]
    s.set_shortlisted(1, False)
    assert s.list("score", shortlisted_only=True) == []


def test_shortlisting_a_missing_seed_reports_false(s):
    assert s.set_shortlisted(99, True) is False


def test_shortlisted_seed_survives_search_trim_and_rescoring(s):
    save(s, 1)
    s.set_shortlisted(1, True)
    s.delete_search_seed(1)
    assert s.get(1) is not None
    save(s, 1, score=70)
    assert s.get(1)["shortlisted"] is True and s.get(1)["score"] == 70


def test_shortlisted_seeds_stay_listed_after_many_search_seeds(s):
    save(s, 1, score=1)
    s.set_shortlisted(1, True)
    for seed in range(100, 700):
        save(s, seed, score=50)
    assert "1" in {r["seed"] for r in s.list("score")}


def test_existing_database_gets_new_columns_and_keeps_rows(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE seeds (seed TEXT PRIMARY KEY, input_text TEXT, score REAL NOT NULL,
        breakdown TEXT NOT NULL, spawn_x INTEGER NOT NULL, spawn_z INTEGER NOT NULL, spawn_biome TEXT NOT NULL,
        mean_weirdness REAL NOT NULL, rejected_reason TEXT, structures TEXT NOT NULL, source TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    old.execute("INSERT INTO seeds VALUES ('5', 'mine', 9, '{}', 0, 0, 'plains', 0, NULL, '[]', 'manual', 'then')")
    old.commit()
    old.close()
    row = Store(path).get(5)
    assert row["input_text"] == "mine" and row["shortlisted"] is False and row["peak_share"] == 0


def test_biome_count_is_saved(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    result = Result(50.0, {"variety": 20.0}, 0.0, None, 0.1, 17)
    store.save(5, None, result, (0, 0), "plains", [], "manual")
    assert store.get(5)["biome_count"] == 17


def test_old_database_gains_biome_count(tmp_path):
    import sqlite3

    path = str(tmp_path / "s.db")
    Store(path)
    db = sqlite3.connect(path)
    db.execute("ALTER TABLE seeds DROP COLUMN biome_count")
    db.commit()
    db.close()
    Store(path)
    assert "biome_count" in {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(seeds)")}
