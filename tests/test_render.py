import os

import numpy as np
import pytest
from PIL import Image

from app import render

SEED = 3874681947099440070


@pytest.mark.parametrize("layer", ["weirdness", "surface", "height"])
def test_png_opens_at_the_small_map(tmp_path, layer):
    with Image.open(render.Layers(str(tmp_path)).path(SEED, layer)) as img:
        assert img.size == (250, 250)


@pytest.mark.parametrize("blocks,pixels", [(1000, 250), (2000, 500), (6144, 1536)])
def test_each_map_size_has_its_own_png(tmp_path, blocks, pixels):
    with Image.open(render.Layers(str(tmp_path)).path(SEED, "surface", blocks)) as img:
        assert img.size == (pixels, pixels)


def test_other_map_sizes_rejected(tmp_path):
    with pytest.raises(ValueError):
        render.Layers(str(tmp_path)).path(SEED, "surface", 4000)


def test_sizes_are_cached_separately(tmp_path):
    layers = render.Layers(str(tmp_path))
    assert layers.path(SEED, "weirdness", 1000) != layers.path(SEED, "weirdness", 2000)


def test_big_map_png_size(tmp_path):
    with Image.open(render.Layers(str(tmp_path)).path(SEED, "weirdness", 6144)) as img:
        assert img.size == (1536, 1536) and img.format == "PNG"


def test_grey_scale_is_fixed():
    grey = render.weirdness_to_grey(np.array([[-1.2, 0.0, 1.2, -5.0, 5.0]]))
    assert grey[0, 0] == 0 and grey[0, 1] in (127, 128) and grey[0, 2] == 255
    assert grey[0, 3] == 0 and grey[0, 4] == 255
    assert grey.dtype == np.uint8


def test_second_call_uses_cache(tmp_path):
    layers = render.Layers(str(tmp_path))
    first = layers.path(SEED, "weirdness")
    stamp = first.stat().st_mtime_ns
    assert layers.path(SEED, "weirdness").stat().st_mtime_ns == stamp


def test_cache_deletes_oldest_over_limit(tmp_path):
    layers = render.Layers(str(tmp_path), max_bytes=1)
    old = layers.path(1, "weirdness")
    os.utime(old, (1, 1))
    new = layers.path(2, "weirdness")
    assert new.exists() and not old.exists()


def test_no_partial_file_left(tmp_path, monkeypatch):
    def broken_save(self, fp, *args, **kwargs):
        with open(fp, "wb") as f:
            f.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", broken_save)
    layers = render.Layers(str(tmp_path))
    with pytest.raises(OSError):
        layers.path(SEED, "weirdness")
    assert list(tmp_path.iterdir()) == []


def test_unknown_layer_rejected(tmp_path):
    with pytest.raises(ValueError):
        render.Layers(str(tmp_path)).path(SEED, "../../etc")


def test_runner_is_used_for_building(tmp_path):
    calls = []

    def run(fn, *args):
        calls.append(fn)
        return fn(*args)

    render.Layers(str(tmp_path), run=run).path(SEED, "weirdness")
    assert calls == [render.build_layer]


def test_surface_png_pixels_match_block_positions(tmp_path):
    from app import cubiomes

    colors = cubiomes.biome_colors()
    with Image.open(render.Layers(str(tmp_path)).path(SEED, "surface", 2000)) as img:
        for px, py in [(0, 0), (499, 0), (0, 499), (300, 200)]:
            biome = cubiomes.surface_grid(SEED, 4, px - 250, py - 250, 1, 1)[0, 0]
            assert tuple(int(c) for c in colors[biome]) == img.getpixel((px, py))


def test_underground_png_is_half_size_and_clear_where_there_are_no_caves(tmp_path):
    from app import cubiomes

    colors = cubiomes.biome_colors()
    with Image.open(render.Layers(str(tmp_path)).path(SEED, "underground", 6144)) as img:
        assert img.size == (768, 768) and img.mode == "RGBA"
        alphas = {pixel[3] for pixel in img.resize((64, 64), Image.NEAREST).getdata()}
        assert alphas == {0, 255}
        for px, py in [(10, 10), (400, 120), (700, 650)]:
            biome = cubiomes.cave_grid(SEED, -768 + px * 2, -768 + py * 2, 1, 1, 1)[0, 0]
            expected = (0, 0, 0, 0) if biome < 0 else (*(int(c) for c in colors[biome]), 255)
            assert img.getpixel((px, py)) == expected


def test_height_png_pixels_match_block_positions(tmp_path):
    from app import cubiomes

    with Image.open(render.Layers(str(tmp_path)).path(SEED, "height", 2000)) as img:
        for px, py in [(0, 0), (499, 0), (300, 200)]:
            height = cubiomes.height_grid(SEED, px - 250, py - 250, 1, 1, 1)
            assert tuple(int(c) for c in render.height_to_rgb(height)[0, 0]) == img.getpixel((px, py))


def test_height_colours_are_fixed_so_seeds_can_be_compared():
    low, sea, land, peak = render.height_to_rgb(np.array([[-20.0, 62.0, 70.0, 400.0]]))[0]
    assert low[2] > low[0] and sea[2] > sea[0], "water should be blue"
    assert land[1] > land[2], "low land should be green"
    assert tuple(peak) == (255, 255, 255)
