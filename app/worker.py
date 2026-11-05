"""Runs cubiomes work in separate processes, so a native crash can't take down the web app."""

import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass

import numpy as np

from app import cubiomes, render
from app.scoring import Result, WorldFacts, evaluate, terrain_hint

GRID_CELLS = 256
GRID_ORIGIN_16 = -GRID_CELLS // 2
GRID_Y_4 = render.MAP_Y_4  # cubiomes keeps vertical units at 1:4 at every horizontal scale
CELL_BLOCKS = 16


class WorkerCrashed(RuntimeError):
    pass


@dataclass
class Scored:
    seed: int
    result: Result
    spawn: tuple[int, int]
    spawn_biome: str
    structures: list[tuple[str, int, int]]


_names = None


def _biome_names() -> np.ndarray:
    global _names
    if _names is None:
        _names = np.array([cubiomes.biome_name(i) for i in range(256)], dtype=object)
    return _names


def score_seed(seed: int) -> Scored:
    x, z, biome = cubiomes.spawn(seed)
    biomes = cubiomes.biome_grid(seed, CELL_BLOCKS, GRID_ORIGIN_16, GRID_ORIGIN_16, GRID_CELLS, GRID_CELLS, GRID_Y_4)
    weirdness = cubiomes.weirdness_grid(seed, GRID_ORIGIN_16 * 4, GRID_ORIGIN_16 * 4, GRID_CELLS, GRID_CELLS, 4)
    structures = [(s.kind, s.x, s.z) for s in cubiomes.structures(seed, render.MAP_EDGE_BLOCKS)]
    spawn_biome = cubiomes.biome_name(biome)
    origin = GRID_ORIGIN_16 * CELL_BLOCKS
    facts = WorldFacts(
        spawn=(x, z), spawn_biome=spawn_biome, biomes=_biome_names()[biomes & 255],
        cell_blocks=CELL_BLOCKS, origin_block=(origin, origin), weirdness=weirdness, structures=structures,
    )
    return Scored(seed, evaluate(facts), (x, z), spawn_biome, structures)


def point(seed: int, x: int, z: int) -> dict:
    """The biome and weirdness at one block position, for the map's hover readout."""
    x4, z4 = x >> 2, z >> 2
    weirdness = cubiomes.weirdness_at(seed, x4, z4)
    return {
        "biome": cubiomes.biome_name(cubiomes.biome_at(seed, 4, x4, z4, render.MAP_Y_4)),
        "weirdness": weirdness,
        "terrain": terrain_hint(weirdness),
    }


class Pool:
    def __init__(self, workers: int = 4):
        self.workers = workers
        self._lock = threading.Lock()
        self._executor = self._new_executor()

    def _new_executor(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(self.workers, mp_context=multiprocessing.get_context("spawn"))

    def _replace(self, broken: ProcessPoolExecutor) -> None:
        with self._lock:
            if self._executor is not broken:
                return
            self._executor = self._new_executor()
        processes = list((broken._processes or {}).values())
        broken.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            process.kill()

    def run(self, fn, *args, timeout: float = 120):
        executor = self._executor
        try:
            return executor.submit(fn, *args).result(timeout=timeout)
        except BrokenProcessPool as e:
            self._replace(executor)
            raise WorkerCrashed("A map worker crashed") from e
        except FutureTimeout as e:
            self._replace(executor)
            raise WorkerCrashed(f"A map worker took longer than {timeout} seconds") from e
        except RuntimeError as e:
            if "after shutdown" not in str(e):
                raise
            raise WorkerCrashed("A map worker was restarting") from e
