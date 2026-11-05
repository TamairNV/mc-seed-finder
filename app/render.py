"""Turns cubiomes grids into cached PNG layers for the map."""

import os
import pathlib
import tempfile

import numpy as np
from PIL import Image

from app import cubiomes

MAP_SIZES = (1000, 2000, 6144)  # blocks across, centred on 0,0. Each pixel covers 4 blocks.
MAP_DEFAULT = MAP_SIZES[0]
MAP_EDGE_BLOCKS = MAP_SIZES[-1] // 2
CAVE_STEP = 2  # the underground layer is half resolution, because each column takes several readings
GREY_RANGE = 1.2  # fixed so brightness can be compared between seeds
LAYERS = {"weirdness", "surface", "underground", "height"}
# Height in blocks to colour. Fixed so colours can be compared between seeds.
HEIGHT_STOPS = (
    (30, (12, 42, 110)), (62, (64, 134, 204)), (64, (86, 158, 84)), (100, (176, 190, 96)),
    (140, (150, 108, 68)), (180, (150, 150, 150)), (220, (255, 255, 255)),
)


def weirdness_to_grey(grid: np.ndarray) -> np.ndarray:
    scaled = (np.clip(grid, -GREY_RANGE, GREY_RANGE) + GREY_RANGE) / (2 * GREY_RANGE) * 255
    return np.rint(scaled).astype(np.uint8)


def height_to_rgb(grid: np.ndarray) -> np.ndarray:
    heights = [stop[0] for stop in HEIGHT_STOPS]
    channels = [np.interp(grid, heights, [stop[1][c] for stop in HEIGHT_STOPS]) for c in range(3)]
    return np.rint(np.stack(channels, axis=-1)).astype(np.uint8)


def _image(seed: int, layer: str, blocks: int) -> Image.Image:
    pixels = blocks // 4
    origin = -pixels // 2
    if layer == "weirdness":
        grid = cubiomes.weirdness_grid(seed, origin, origin, pixels, pixels, 1)
        return Image.fromarray(weirdness_to_grey(grid), "L")
    if layer == "height":
        grid = cubiomes.height_grid(seed, origin, origin, pixels, pixels, 1)
        return Image.fromarray(height_to_rgb(grid), "RGB")
    if layer == "underground":
        size = pixels // CAVE_STEP
        grid = cubiomes.cave_grid(seed, origin, origin, size, size, CAVE_STEP)
        alpha = np.where(grid >= 0, 255, 0).astype(np.uint8)[..., None]
        rgb = np.where(alpha > 0, cubiomes.biome_colors()[grid & 255], 0).astype(np.uint8)
        return Image.fromarray(np.concatenate([rgb, alpha], axis=-1), "RGBA")
    grid = cubiomes.surface_grid(seed, 4, origin, origin, pixels, pixels)
    return Image.fromarray(cubiomes.biome_colors()[grid & 255], "RGB")


def build_layer(target: str, seed: int, layer: str, blocks: int = MAP_DEFAULT) -> None:
    """Writes the PNG in full before it takes the final name. Runs in a worker process."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".tmp")
    os.close(fd)
    try:
        _image(seed, layer, blocks).save(tmp, format="PNG")
        os.replace(tmp, target)
    except BaseException:
        os.unlink(tmp)
        raise


def _run_here(fn, *args):
    return fn(*args)


class Layers:
    def __init__(self, cache_dir: str, max_bytes: int = 500 * 1024 * 1024, run=_run_here):
        self._dir = pathlib.Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._run = run

    def path(self, seed: int, layer: str, blocks: int = MAP_DEFAULT) -> pathlib.Path:
        if layer not in LAYERS:
            raise ValueError(f"unknown layer {layer!r}")
        if blocks not in MAP_SIZES:
            raise ValueError(f"unknown map size {blocks!r}")
        target = self._dir / f"{seed}_{layer}_{blocks}.png"
        if not target.exists():
            self._run(build_layer, str(target), seed, layer, blocks)
            self._trim(keep=target)
        return target

    def _trim(self, keep: pathlib.Path) -> None:
        entries = [(p.stat().st_mtime_ns, p.stat().st_size, p) for p in self._dir.glob("*.png")]
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries, key=lambda e: e[0]):
            if total <= self._max_bytes:
                break
            if path != keep:
                path.unlink(missing_ok=True)
                total -= size
