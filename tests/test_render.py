import os

import numpy as np
import pytest
from PIL import Image

from app import render

SEED = 3874681947099440070


@pytest.mark.parametrize("layer", ["weirdness", "biomes"])
def test_png_is_1024_square(tmp_path, layer):
    with Image.open(render.Layers(str(tmp_path)).path(SEED, layer)) as img:
        assert img.size == (1024, 1024) and img.format == "PNG"


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
