"""Recalculates every saved seed after a scoring change: python -m app.rescore"""

import os
import pathlib

from app import worker
from app.store import Store


def rescore(store: Store, scorer=worker.score_seed) -> dict:
    rescored = removed = 0
    for row in store.list("score", limit=2**31 - 1):
        seed = int(row["seed"])
        scored = scorer(seed)
        if scored.result.rejected_reason and row["source"] == "search" and not row["shortlisted"]:
            store.delete_search_seed(seed)
            removed += 1
            continue
        store.save(seed, row["input_text"], scored.result, scored.spawn, scored.spawn_biome,
                   scored.structures, row["source"])
        rescored += 1
    return {"rescored": rescored, "removed": removed}


if __name__ == "__main__":
    data = pathlib.Path(os.environ.get("DATA_DIR", "./data"))
    print(rescore(Store(str(data / "seeds.db"))))
