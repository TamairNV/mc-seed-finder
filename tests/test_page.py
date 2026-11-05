from fastapi.testclient import TestClient

from app.main import create_app
from app.render import Layers
from app.search import SearchManager
from app.store import Store
from tests.test_api import AllowAll, FakePool, fake_scorer

SEED = 3874681947099440070


def client(tmp_path):
    pool = FakePool()
    store = Store(str(tmp_path / "s.db"))
    layers = Layers(str(tmp_path / "c"))
    return TestClient(create_app(pool, store, layers, SearchManager(pool, store), AllowAll(), scorer=fake_scorer))


def test_page_has_controls(tmp_path):
    r = client(tmp_path).get("/")
    assert r.status_code == 200
    for element in ["seed-input", "random-btn", "search-btn", "search-count", "stop-btn", "map",
                    "biome-opacity", "seed-list", "breakdown", "structure-toggles"]:
        assert f'id="{element}"' in r.text


def test_page_warns_about_game_version(tmp_path):
    text = client(tmp_path).get("/").text
    assert "1.21 Winter Drop" in text and "26.4" in text


def test_static_files_served(tmp_path):
    c = client(tmp_path)
    assert c.get("/static/app.js").status_code == 200 and c.get("/static/app.css").status_code == 200


def test_point_returns_biome_and_weirdness(tmp_path):
    c = client(tmp_path)
    c.post("/api/seeds", json={"seed": str(SEED)})
    body = c.get(f"/api/seeds/{SEED}/point?x=8&z=8").json()
    assert body["biome"] == "meadow" and isinstance(body["weirdness"], float)


def test_point_outside_map_is_422(tmp_path):
    c = client(tmp_path)
    c.post("/api/seeds", json={"seed": str(SEED)})
    assert c.get(f"/api/seeds/{SEED}/point?x=5000&z=0").status_code == 422


def test_point_for_unsaved_seed_is_404(tmp_path):
    assert client(tmp_path).get("/api/seeds/5/point?x=0&z=0").status_code == 404
