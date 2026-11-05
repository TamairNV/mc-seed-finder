"""The single background search: scores random seeds and keeps the best in the store."""

import heapq
import logging
import secrets
import threading

from app import worker

KEEP = 100
FLUSH_EVERY = 50

log = logging.getLogger(__name__)


class AlreadyRunning(RuntimeError):
    pass


def random_seed() -> int:
    value = secrets.randbits(64)
    return value - 2**64 if value >= 2**63 else value


class SearchManager:
    def __init__(self, pool, store, scorer=worker.score_seed):
        self._pool = pool
        self._store = store
        self._scorer = scorer
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._stop = threading.Event()
        self._running = False
        self._tried = self._target = self._claimed = 0
        self._error = None
        self._stopped_early = False
        self._top: list[tuple[float, int, worker.Scored]] = []
        self._order = 0
        self._saved: set[int] = set()
        self._best: worker.Scored | None = None

    def start(self, count: int) -> None:
        with self._lock:
            if self._running:
                raise AlreadyRunning("A search is already running")
            self._running = True
            self._tried = self._claimed = 0
            self._target = count
            self._error = None
            self._stopped_early = False
            self._top = []
            self._saved = set()
            self._best = None
            self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "tried": self._tried,
                "target": self._target,
                "best_seed": str(self._best.seed) if self._best else None,
                "best_score": self._best.result.score if self._best else None,
                "stopped_early": self._stopped_early,
                "error": self._error,
            }

    def _run(self) -> None:
        threads = [threading.Thread(target=self._work) for _ in range(self._pool.workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            self._flush()
        except Exception as e:
            log.exception("search flush failed")
            with self._lock:
                self._error = str(e)
        with self._lock:
            self._stopped_early = self._tried < self._target
            self._running = False

    def _work(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if self._claimed >= self._target:
                    return
                self._claimed += 1
            try:
                scored = self._pool.run(self._scorer, random_seed())
            except Exception as e:
                log.warning("search seed failed: %s", e)
                with self._lock:
                    self._error = str(e)
                    self._tried += 1
                continue
            with self._lock:
                self._tried += 1
                self._keep(scored)
                flush = self._tried % FLUSH_EVERY == 0
            if flush:
                try:
                    self._flush()
                except Exception as e:
                    log.exception("search flush failed")
                    with self._lock:
                        self._error = str(e)

    def _keep(self, scored: worker.Scored) -> None:
        if scored.result.rejected_reason:
            return
        self._order += 1
        heapq.heappush(self._top, (scored.result.score, self._order, scored))
        if len(self._top) > KEEP:
            heapq.heappop(self._top)
        if self._best is None or scored.result.score > self._best.result.score:
            self._best = scored

    def _flush(self) -> None:
        with self._flush_lock:
            with self._lock:
                top = [entry[2] for entry in self._top]
            keep = {s.seed for s in top}
            for scored in top:
                if scored.seed not in self._saved:
                    self._store.save(scored.seed, None, scored.result, scored.spawn, scored.spawn_biome,
                                     scored.structures, "search")
                    self._saved.add(scored.seed)
            for seed in self._saved - keep:
                self._store.delete_search_seed(seed)
                self._saved.discard(seed)
