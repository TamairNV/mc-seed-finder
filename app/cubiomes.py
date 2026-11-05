"""ctypes wrapper over native/seedlib.c, returning plain Python and numpy data."""

import ctypes as c
import os
from dataclasses import dataclass

import numpy as np

_MAX_STRUCTURES = 4096


class _SlStructure(c.Structure):
    _fields_ = [("kind", c.c_int), ("x", c.c_int), ("z", c.c_int)]


_lib = c.CDLL(os.environ.get("SEEDLIB_PATH", "/opt/seedlib.so"))
_int_p = c.POINTER(c.c_int)
_lib.sl_spawn.argtypes = [c.c_int64, _int_p, _int_p, _int_p]
_lib.sl_spawn.restype = None
_lib.sl_biome_grid.argtypes = [c.c_int64, *[c.c_int] * 6, _int_p]
_lib.sl_biome_at.argtypes = [c.c_int64, *[c.c_int] * 4]
_lib.sl_surface_grid.argtypes = [c.c_int64, *[c.c_int] * 5, _int_p]
_lib.sl_height_grid.argtypes = [c.c_int64, *[c.c_int] * 5, c.POINTER(c.c_float)]
_lib.sl_height_grid.restype = None
_lib.sl_cave_grid.argtypes = [c.c_int64, *[c.c_int] * 5, _int_p]
_lib.sl_cave_grid.restype = None
_lib.sl_weirdness_grid.argtypes = [c.c_int64, *[c.c_int] * 5, c.POINTER(c.c_double)]
_lib.sl_weirdness_grid.restype = None
_lib.sl_weirdness_at.argtypes = [c.c_int64, c.c_int, c.c_int]
_lib.sl_weirdness_at.restype = c.c_double
_lib.sl_structures.argtypes = [c.c_int64, c.c_int, c.POINTER(_SlStructure), c.c_int]
_lib.sl_structure_name.argtypes = [c.c_int]
_lib.sl_structure_name.restype = c.c_char_p
_lib.sl_biome_name.argtypes = [c.c_int]
_lib.sl_biome_name.restype = c.c_char_p
_lib.sl_biome_colors.argtypes = [c.POINTER(c.c_ubyte)]
_lib.sl_biome_colors.restype = None


@dataclass(frozen=True)
class Structure:
    kind: str
    x: int
    z: int


def spawn(seed: int) -> tuple[int, int, int]:
    x, z, biome = c.c_int(), c.c_int(), c.c_int()
    _lib.sl_spawn(seed, c.byref(x), c.byref(z), c.byref(biome))
    return x.value, z.value, biome.value


def biome_grid(seed: int, scale: int, x: int, z: int, w: int, h: int, y: int) -> np.ndarray:
    out = np.empty((h, w), dtype=np.int32)
    err = _lib.sl_biome_grid(seed, scale, x, z, w, h, y, out.ctypes.data_as(_int_p))
    if err:
        raise RuntimeError(f"biome generation failed with code {err}")
    return out


def surface_grid(seed: int, scale: int, x: int, z: int, w: int, h: int) -> np.ndarray:
    """Biomes on top of the land, never a cave biome. scale is 4 or 16."""
    out = np.empty((h, w), dtype=np.int32)
    err = _lib.sl_surface_grid(seed, scale, x, z, w, h, out.ctypes.data_as(_int_p))
    if err:
        raise RuntimeError(f"biome generation failed with code {err}")
    return out


def height_grid(seed: int, x4: int, z4: int, w: int, h: int, step: int) -> np.ndarray:
    """Approximate terrain height in blocks, sampled every `step` cells of 1:4 coordinates."""
    out = np.empty((h, w), dtype=np.float32)
    _lib.sl_height_grid(seed, x4, z4, w, h, step, out.ctypes.data_as(c.POINTER(c.c_float)))
    return out


def cave_grid(seed: int, x4: int, z4: int, w: int, h: int, step: int) -> np.ndarray:
    """The deepest cave biome under each column, or -1 where there is none."""
    out = np.empty((h, w), dtype=np.int32)
    _lib.sl_cave_grid(seed, x4, z4, w, h, step, out.ctypes.data_as(_int_p))
    return out


def biome_at(seed: int, scale: int, x: int, z: int, y: int) -> int:
    return _lib.sl_biome_at(seed, scale, x, z, y)


def weirdness_grid(seed: int, x4: int, z4: int, w: int, h: int, step: int) -> np.ndarray:
    out = np.empty((h, w), dtype=np.float64)
    _lib.sl_weirdness_grid(seed, x4, z4, w, h, step, out.ctypes.data_as(c.POINTER(c.c_double)))
    return out


def weirdness_at(seed: int, x4: int, z4: int) -> float:
    return _lib.sl_weirdness_at(seed, x4, z4)


def structures(seed: int, radius: int = 2048) -> list[Structure]:
    buf = (_SlStructure * _MAX_STRUCTURES)()
    n = _lib.sl_structures(seed, radius, buf, _MAX_STRUCTURES)
    if n < 0:
        raise RuntimeError("too many structures for buffer")
    return [Structure(_lib.sl_structure_name(s.kind).decode(), s.x, s.z) for s in buf[:n]]


def biome_name(biome_id: int) -> str:
    return _lib.sl_biome_name(biome_id).decode()


def biome_colors() -> np.ndarray:
    out = np.empty((256, 3), dtype=np.uint8)
    _lib.sl_biome_colors(out.ctypes.data_as(c.POINTER(c.c_ubyte)))
    return out
