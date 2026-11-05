import pytest
from fastapi.testclient import TestClient

from app.auth import AccessVerifier, Denied
from app.main import create_app
from app.render import Layers
from app.scoring import Result
from app.search import SearchManager
from app.store import Store
from app.worker import Scored, WorkerCrashed

SEED = 3874681947099440070


class AllowAll:
    def __init__(self, role="admin"):
        self.role = role

    def verify(self, token):
        return {"role": self.role}


class FakePool:
    workers = 2

    def run(self, fn, *args, timeout=None):
        return fn(*args)


def fake_scorer(seed):
    result = Result(40.0, {"terrain": 1.0}, 0.1, None)
    return Scored(seed, result, (8, 8), "meadow", [("Village", 1, 2)])


def taiga_scorer(seed):
    result = Result(0.0, {"terrain": 1.0}, 0.1, "Spawns in a spruce biome (taiga)")
    return Scored(seed, result, (8, 8), "taiga", [])


def crashing_scorer(seed):
    raise WorkerCrashed("A map worker crashed")


def build(tmp_path, scorer=fake_scorer, verifier=None, search=None):
    pool = FakePool()
    store = Store(str(tmp_path / "seeds.db"))
    layers = Layers(str(tmp_path / "cache"), run=lambda fn, *a: pool.run(fn, *a))
    search = search or SearchManager(pool, store, scorer=fake_scorer)
    app = create_app(pool, store, layers, search, verifier or AllowAll(), scorer=scorer)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path):
    return build(tmp_path)


def test_big_seed_stays_exact_as_string(client):
    r = client.post("/api/seeds", json={"seed": "9007199254740993"})
    assert r.status_code == 200 and r.json()["seed"] == "9007199254740993"
    assert client.get("/api/seeds/9007199254740993").json()["seed"] == "9007199254740993"
    assert client.get("/api/seeds").json()[0]["seed"] == "9007199254740993"


def test_seed_as_json_number_is_refused(client):
    assert client.post("/api/seeds", json={"seed": 9007199254740993}).status_code == 422


def test_text_seed_is_saved_with_its_text(client):
    row = client.post("/api/seeds", json={"seed": "hello"}).json()
    assert row["seed"] == "99162322" and row["input_text"] == "hello" and row["source"] == "manual"


def test_random_seed(client):
    row = client.post("/api/seeds", json={"random": True}).json()
    assert client.get(f"/api/seeds/{row['seed']}").status_code == 200 and row["input_text"] is None


def test_rejected_seed_keeps_map_and_breakdown(tmp_path):
    client = build(tmp_path, scorer=taiga_scorer)
    row = client.post("/api/seeds", json={"seed": "5"}).json()
    assert row["rejected_reason"] and row["breakdown"]
    for layer in ("weirdness", "surface", "underground", "height"):
        r = client.get(f"/api/seeds/5/layers/{layer}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_invalid_seed_is_400_and_not_saved(client):
    assert client.post("/api/seeds", json={"seed": "   "}).status_code == 400
    assert client.post("/api/seeds", json={}).status_code == 400
    assert client.get("/api/seeds").json() == []


def test_seed_above_64_bits_in_url_is_400(client):
    assert client.get("/api/seeds/9223372036854775808").status_code == 400
    assert client.get("/api/seeds/9223372036854775808/layers/surface.png").status_code == 400


def test_text_in_seed_url_is_400(client):
    assert client.get("/api/seeds/hello").status_code == 400


def test_unsaved_seed_is_404(client):
    assert client.get("/api/seeds/5").status_code == 404


def test_layers_unknown_layer_is_404(client):
    client.post("/api/seeds", json={"seed": "5"})
    assert client.get("/api/seeds/5/layers/nope.png").status_code == 404


def test_layers_for_unsaved_seed_is_404(client):
    assert client.get("/api/seeds/5/layers/surface.png").status_code == 404


def test_worker_crash_returns_500_with_message(tmp_path):
    client = build(tmp_path, scorer=crashing_scorer)
    r = client.post("/api/seeds", json={"seed": "5"})
    assert r.status_code == 500 and "crashed" in r.json()["detail"]
    assert client.get("/api/seeds").json() == []


def test_sort_values(client):
    assert client.get("/api/seeds?sort=peak").status_code == 200
    assert client.get("/api/seeds?sort=nope").status_code == 422


@pytest.mark.parametrize("count", [0, -1, 100001])
def test_search_count_out_of_range_is_422(client, count):
    assert client.post("/api/search", json={"count": count}).status_code == 422


def test_search_runs_and_reports(client):
    assert client.post("/api/search", json={"count": 3}).status_code == 202
    assert set(client.get("/api/search").json()) >= {"running", "tried", "target"}
    assert client.post("/api/search/stop").status_code == 200


@pytest.mark.parametrize("claims", [{"role": "user"}, {}])
@pytest.mark.parametrize("path,body", [("/api/search", {"count": 1}), ("/api/search/stop", None)])
def test_only_admins_start_or_stop_searches(tmp_path, claims, path, body):
    class Search:
        def __getattr__(self, name):
            raise AssertionError("touched the search")

    class Verifier:
        def verify(self, token):
            return claims
    assert build(tmp_path, verifier=Verifier(), search=Search()).post(path, json=body).status_code == 403


def test_users_can_still_read_search_status_and_add_seeds(tmp_path):
    client = build(tmp_path, verifier=AllowAll("user"))
    assert client.get("/api/search").status_code == 200
    assert client.post("/api/seeds", json={"seed": "5"}).status_code == 200


def test_page_hides_search_controls_from_users(tmp_path):
    assert '<div class="search" hidden>' in build(tmp_path, verifier=AllowAll("user")).get("/").text
    assert '<div class="search">' in build(tmp_path, verifier=AllowAll("admin")).get("/").text


def test_second_search_is_409(tmp_path):
    class Busy:
        def start(self, count):
            from app.search import AlreadyRunning
            raise AlreadyRunning("A search is already running")

    assert build(tmp_path, search=Busy()).post("/api/search", json={"count": 1}).status_code == 409


class DenyAll:
    def verify(self, token):
        raise Denied(403, "Missing Cloudflare Access token")


@pytest.mark.parametrize("path", ["/", "/api/seeds", "/api/search", "/api/seeds/5/layers/surface.png"])
def test_requests_without_token_are_403(tmp_path, path):
    assert build(tmp_path, verifier=DenyAll()).get(path).status_code == 403


def test_healthz_needs_no_token(tmp_path):
    assert build(tmp_path, verifier=DenyAll()).get("/healthz").json() == {"status": "ok"}


def test_token_header_reaches_verifier(tmp_path):
    seen = []

    class Record:
        def verify(self, token):
            seen.append(token)
            return {}

    build(tmp_path, verifier=Record()).get("/api/seeds", headers={"Cf-Access-Jwt-Assertion": "abc"})
    assert seen == ["abc"]


def test_key_endpoint_failure_returns_503(tmp_path):
    import jwt

    class Down:
        def get_signing_key_from_jwt(self, token):
            raise jwt.exceptions.PyJWKClientConnectionError("down")

    client = build(tmp_path, verifier=AccessVerifier("t.example.com", "aud", jwks_client=Down()))
    assert client.get("/api/seeds", headers={"Cf-Access-Jwt-Assertion": "abc"}).status_code == 503


def test_unset_access_config_returns_503(tmp_path):
    client = build(tmp_path, verifier=AccessVerifier(None, None))
    assert client.get("/api/seeds", headers={"Cf-Access-Jwt-Assertion": "abc"}).status_code == 503


@pytest.mark.parametrize("host", ["x/healthz?", "x/healthz#", "x/healthz"])
def test_crafted_host_header_cannot_skip_the_token_check(tmp_path, host):
    client = build(tmp_path, verifier=DenyAll())
    assert client.get("/api/seeds", headers={"Host": host}).status_code == 403


def test_shortlist_route_and_filter(client):
    client.post("/api/seeds", json={"seed": "1"})
    client.post("/api/seeds", json={"seed": "2"})
    r = client.put("/api/seeds/2/shortlist", json={"shortlisted": True})
    assert r.status_code == 200 and r.json()["shortlisted"] is True
    assert [row["seed"] for row in client.get("/api/seeds?shortlist=true").json()] == ["2"]
    assert len(client.get("/api/seeds").json()) == 2


def test_shortlist_unsaved_seed_is_404(client):
    assert client.put("/api/seeds/5/shortlist", json={"shortlisted": True}).status_code == 404


def test_shortlist_bad_seed_is_400(client):
    assert client.put("/api/seeds/hello/shortlist", json={"shortlisted": True}).status_code == 400


def test_old_biomes_layer_name_is_gone(client):
    # its cached images read the map at y=60, so they must not be served any more
    client.post("/api/seeds", json={"seed": "5"})
    assert client.get("/api/seeds/5/layers/biomes.png").status_code == 404


def test_layers_can_be_requested_at_each_map_size(client):
    client.post("/api/seeds", json={"seed": "5"})
    for blocks in (1000, 2000):
        r = client.get(f"/api/seeds/5/layers/surface.png?blocks={blocks}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_layers_refuse_other_map_sizes(client):
    client.post("/api/seeds", json={"seed": "5"})
    assert client.get("/api/seeds/5/layers/surface.png?blocks=4000").status_code == 404
