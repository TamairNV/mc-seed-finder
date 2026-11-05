from app.rescore import rescore
from app.scoring import Result
from app.store import Store
from app.worker import Scored


def scorer(score=80.0, reason=None):
    def run(seed):
        return Scored(seed, Result(score, {"terrain": 1.0}, 0.0, reason, 0.2), (1, 2), "meadow", [])
    return run


def seeded(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    old = Result(10.0, {}, 0.0, None)
    store.save(1, "mine", old, (0, 0), "plains", [], "manual")
    store.save(2, None, old, (0, 0), "plains", [], "search")
    store.save(3, None, old, (0, 0), "plains", [], "search")
    store.set_shortlisted(3, True)
    return store


def test_rescore_updates_values_and_keeps_identity(tmp_path):
    store = seeded(tmp_path)
    assert rescore(store, scorer()) == {"rescored": 3, "removed": 0}
    row = store.get(1)
    assert row["score"] == 80 and row["peak_share"] == 0.2 and row["spawn_biome"] == "meadow"
    assert row["source"] == "manual" and row["input_text"] == "mine"
    assert store.get(3)["shortlisted"] is True


def test_newly_rejected_seeds_only_leave_if_search_found_and_not_shortlisted(tmp_path):
    store = seeded(tmp_path)
    assert rescore(store, scorer(0.0, "Spawns in a spruce biome (taiga)")) == {"rescored": 2, "removed": 1}
    assert store.get(1)["rejected_reason"] and store.get(3)["rejected_reason"]
    assert store.get(2) is None
