# Seed Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private web app that scores Minecraft Java seeds, maps them, and automatically finds good ones for Tamair's server.

**Architecture:** A single FastAPI container calls a small C library over cubiomes through `ctypes`, inside worker processes so native crashes stay contained. Scoring is a pure Python function over plain world facts, SQLite holds results, and PNG layers are cached on disk.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, numpy, Pillow, PyJWT[crypto], httpx (tests), pytest, gcc, cubiomes `e61f905`, SQLite, Docker Compose, Cloudflare Access.

**Spec:** `docs/superpowers/specs/2026-11-05-seed-finder-design.md`

## Global Constraints

- Cubiomes is pinned to commit `e61f905` and targets `MC_NEWEST` (`MC_1_21_WD`).
- All automated tests run in Docker: `docker build -q --target test -t seed-finder-test . && docker run --rm seed-finder-test pytest <path> -v`. Below, this is written as `TEST <path>`.
- The map covers 4096×4096 blocks centred on 0,0, at 1024×1024 pixels (scale 1:4, surface `y=15`). Scoring grids are 256×256 at 1:16 (`y=15`, because cubiomes keeps vertical units at 1:4 at every horizontal scale).
- Seeds are signed 64-bit integers, and are JSON strings in every API request and response.
- Never write secret values anywhere. `.env` holds `CF_TEAM_DOMAIN` and `CF_AUD`, and `.env.example` lists names only.
- Container: `127.0.0.1:8103:8000`, `cpus: 4`, `mem_limit: 2g`, uid/gid 1000, `TZ=Europe/London`, `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `no-new-privileges`, state in `./data`.
- Back up to `~/backups/<thing>_<YYYYMMDD-HHMMSS>` before changing anything that already exists.
- End commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A search stopped early or a restart mid-search should keep the best seeds found so far. Test in Task 5.
- Entering a seed that a search already found should update one row, with no duplicate and no lost `manual` status. Test in Task 3.
- Numbers above 2^53 must survive the trip through the API and page unchanged. Test in Task 7.
- A rejected spruce or ocean seed must still open its map and breakdown. Test in Task 7.
- If Cloudflare's key endpoint is down, or `CF_AUD` is unset, requests must be refused, never allowed through. Test in Task 7.

---

### Task 1: Project setup and native cubiomes wrapper

**Files:**
- Create: `.gitignore`, `requirements.txt`, `Dockerfile`, `native/seedlib.c`, `app/__init__.py`, `app/cubiomes.py`
- Test: `tests/test_cubiomes.py`

**Interfaces:**
- Produces, in `app/cubiomes.py`:
  - `Structure` dataclass: `kind: str, x: int, z: int`. `kind` is the cubiomes name, such as `"Village"`.
  - `spawn(seed: int) -> tuple[int, int, int]`: returns `(x, z, biome_id)`.
  - `biome_grid(seed: int, scale: int, x: int, z: int, w: int, h: int, y: int) -> np.ndarray`: `int32`, shape `(h, w)`, in scaled coordinates.
  - `weirdness_grid(seed: int, x4: int, z4: int, w: int, h: int, step: int) -> np.ndarray`: `float64`, shape `(h, w)`, in 1:4 coordinates, sampled every `step` cells.
  - `structures(seed: int, radius: int = 2048) -> list[Structure]`: the 9 spec types within `radius` on each axis, which pass `isViableStructurePos`.
  - `biome_at(seed: int, scale: int, x: int, z: int, y: int) -> int` and `weirdness_at(seed: int, x4: int, z4: int) -> float`: direct C single-point calls, used to check grids.
  - `biome_name(biome_id: int) -> str` and `biome_colors() -> np.ndarray`: `uint8`, shape `(256, 3)`.

- [ ] **Step 1: Run `openwolf init` in the project root.** The server doesn't have it, so install it first with `npm install -g openwolf` (Node 20+). If Node is missing or too old, stop and report it. Check the existing repo files are intact afterwards.

- [ ] **Step 2: Write a multi-stage `Dockerfile`.** Stage `native`: `gcc` and `git`, clone cubiomes, check out `e61f905`, build `/opt/seedlib.so` from `native/seedlib.c` and all cubiomes `.c` files except `tests.c`, using `-O3 -fwrapv -shared -fPIC`. Stage `base`: `python:3.12-slim`, install `requirements.txt`, copy the library and `app/`. Stage `test`: `base` plus `tests/` and pytest. Final stage `app`: runs uvicorn on port 8000 with `SEEDLIB_PATH=/opt/seedlib.so`.

- [ ] **Step 3: Write the failing tests** in `tests/test_cubiomes.py`:

```python
SEED = 3874681947099440070  # spawned in meadow during the feasibility test

def test_same_seed_gives_identical_results():
    assert cubiomes.spawn(SEED) == cubiomes.spawn(SEED)
    assert (cubiomes.biome_grid(SEED, 16, -128, -128, 32, 32, 4)
            == cubiomes.biome_grid(SEED, 16, -128, -128, 32, 32, 4)).all()

def test_spawn_matches_feasibility_result():
    x, z, biome = cubiomes.spawn(SEED)
    assert (x, z) == (8, 8) and cubiomes.biome_name(biome) == "meadow"

def test_biome_grid_axes_and_scale_match_direct_call():
    grid = cubiomes.biome_grid(SEED, 4, -512, -512, 64, 32, 15)
    assert grid.shape == (32, 64)
    assert grid[7, 50] == cubiomes.biome_at(SEED, 4, -512 + 50, -512 + 7, 15)

def test_weirdness_grid_axes_and_step_match_direct_call():
    grid = cubiomes.weirdness_grid(SEED, -512, -512, 64, 32, 4)
    assert grid.shape == (32, 64)
    assert grid[7, 50] == cubiomes.weirdness_at(SEED, -512 + 50 * 4, -512 + 7 * 4)

def test_structures_are_in_range_and_known_kinds():
    found = cubiomes.structures(SEED)
    assert found and all(abs(s.x) < 2048 and abs(s.z) < 2048 for s in found)
    assert {s.kind for s in found} <= KNOWN_KINDS

def test_negative_seed_is_accepted():
    assert cubiomes.spawn(-1) == cubiomes.spawn(-1)
```

- [ ] **Step 4: Run** `TEST tests/test_cubiomes.py`. Expected: FAIL because the functions don't exist yet.

- [ ] **Step 5: Implement `native/seedlib.c` and `app/cubiomes.py`.** Export one `sl_` C function per interface above, creating the `Generator` per call so calls share no state. Use `setClimateParaSeed(&bn, seed, 0, NP_WEIRDNESS, -1)` and `sampleClimatePara(&bn, NULL, x, z)` for weirdness. These skip Minecraft's small coordinate shift, which is acceptable for a map at this scale. Region loop as in the feasibility test: `rs = sc.regionSize * 16`, from `-radius / rs - 1` to `radius / rs`.

- [ ] **Step 6: Run** `TEST tests/test_cubiomes.py`. Expected: PASS.

- [ ] **Step 7: Commit** with message `feat: add cubiomes native wrapper`.

### Task 2: Seed parsing and scoring

**Files:**
- Create: `app/seeds.py`, `app/scoring.py`
- Test: `tests/test_seeds.py`, `tests/test_scoring.py`

**Interfaces:**
- Consumes: nothing. `scoring.py` must not import `cubiomes`.
- Produces:
  - `seeds.parse(text: str) -> int`, raising `seeds.InvalidSeed(message)`.
  - `scoring.WorldFacts` dataclass: `spawn: tuple[int, int]`, `spawn_biome: str`, `biomes: np.ndarray` (biome name per cell, 1:16), `cell_blocks: int`, `origin_block: tuple[int, int]`, `weirdness: np.ndarray`, `structures: list[tuple[str, int, int]]`.
  - `scoring.Result` dataclass: `score: float`, `breakdown: dict[str, float]`, `mean_weirdness: float`, `rejected_reason: str | None`.
  - `scoring.evaluate(facts: WorldFacts) -> Result`. Rejected seeds have `score == 0` and a full breakdown.

- [ ] **Step 1: Write the failing tests** with these cases:

```python
@pytest.mark.parametrize("text,seed", [
    ("hello", 99162322),
    ("polygenelubricants", -2147483648),
    ("  123  ", 123),
    ("-5", -5),
    ("9223372036854775807", 9223372036854775807),
])
def test_parse(text, seed): assert seeds.parse(text) == seed

@pytest.mark.parametrize("text", ["", "   ", "9223372036854775808"])
def test_parse_rejects(text):
    with pytest.raises(seeds.InvalidSeed): seeds.parse(text)
```

Scoring, using a `facts(**overrides)` helper over a small uniform `plains` world:

```python
@pytest.mark.parametrize("biome", ["taiga", "snowy_taiga", "old_growth_pine_taiga",
    "old_growth_spruce_taiga", "ocean", "deep_cold_ocean"])
def test_bad_spawn_rejected(biome):
    r = evaluate(facts(spawn_biome=biome))
    assert r.score == 0 and r.rejected_reason and r.breakdown

def test_component_maximums():  # each component stays within spec maximums
    b = evaluate(richest_possible_facts()).breakdown
    assert b["spawn_biome"] == 20 and b["variety"] == 15 and b["rare_biomes"] == 25
    assert b["structures"] == 30 and b["terrain"] == 10
    assert evaluate(richest_possible_facts()).score == 100

def test_closer_structure_scores_more(): ...      # Village at 100 blocks beats 1500
def test_many_villages_do_not_exceed_cap(): ...   # 50 villages score the same as 1 at that distance
def test_closer_rare_biome_scores_more(): ...
def test_terrain_uses_peaks_formula():            # W = 2/3 scores 10, W = 0 scores 0
    ...
def test_mean_weirdness_not_in_score():           # same PV, opposite sign: same score, different mean
    ...
```

- [ ] **Step 2: Run** `TEST tests/test_seeds.py tests/test_scoring.py`. Expected: FAIL because the modules don't exist.

- [ ] **Step 3: Implement `seeds.parse`.** Strip whitespace. If the text matches `-?\d+`, parse it as a number and raise `InvalidSeed` when it falls outside signed 64-bit. Otherwise use Java `String.hashCode`, as a signed 32-bit result over UTF-16 code units.

- [ ] **Step 4: Implement `scoring.evaluate`** with these values, kept as constants at the top of the file. Here `near(d) = max(0, 1 - d / 2048)`, and `d` is the block distance from spawn to the nearest matching cell or structure.
  - Spawn biome: 20 for `cherry_grove`, `meadow`, `mushroom_fields`, `badlands`, `eroded_badlands`, `wooded_badlands`. 12 for `plains`, `savanna`, `jungle`, `birch_forest`. Otherwise 5.
  - Variety: `15 * clamp((distinct - 30) / 25, 0, 1)`. The 30 to 55 range comes from the 40 to 53 seen in the feasibility test.
  - Rare biomes, total capped at 25: `weight * near(d)`, with weights `mushroom_fields` 6, `cherry_grove` 4, `ice_spikes` 4, `eroded_badlands` 4, `pale_garden` 3, `badlands` 2, `bamboo_jungle` 2, `jagged_peaks` 2, `mangrove_swamp` 2, `old_growth_birch_forest` 2.
  - Structures, using only the nearest of each type: `weight * near(d)`, with weights `Village` 8, `Trial_Chambers` 6, `Mansion` 5, `Ancient_City` 4, `Monument` 3, `Desert_Pyramid` 1, `Jungle_Temple` 1, `Outpost` 1, `Trail_Ruins` 1.
  - Terrain: `10 * min(1, share / 0.30)`, where `share` is the fraction of cells with `1 - abs(3 * abs(W) - 2) >= 0.7`.
  - Rejection: the four taiga biomes and any biome whose name contains `ocean`.

- [ ] **Step 5: Run** the same tests. Expected: PASS.

- [ ] **Step 6: Commit** with message `feat: add seed parsing and scoring`.

### Task 3: SQLite store

**Files:**
- Create: `app/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `scoring.Result`.
- Produces: `store.Store(path: str)` with:
  - `save(seed: int, input_text: str | None, result: Result, spawn: tuple[int, int], spawn_biome: str, structures: list[tuple[str, int, int]], source: str) -> None`
  - `get(seed: int) -> dict | None` and `list(sort: str, limit: int = 500) -> list[dict]`. `sort` is `"score"` or `"weirdness"`, and rows use the spec's column names with `seed` as a string.

- [ ] **Step 1: Write the failing tests:** `test_save_and_get_round_trip` (including `breakdown` and `structures` as parsed JSON), `test_sort_orders_highest_first` (both sorts, rejected seeds last under `score`), `test_seed_stays_exact` (`9007199254740993` comes back as `"9007199254740993"`), `test_negative_seed`, and:

```python
def test_resaving_updates_one_row_and_manual_wins():
    s.save(SEED, None, result, (0, 0), "plains", [], "search")
    s.save(SEED, "my seed", result, (0, 0), "plains", [], "manual")
    s.save(SEED, None, result, (0, 0), "plains", [], "search")
    row = s.get(SEED)
    assert row["source"] == "manual" and row["input_text"] == "my seed"
    assert len(s.list("score")) == 1
```

- [ ] **Step 2: Run** `TEST tests/test_store.py`. Expected: FAIL.

- [ ] **Step 3: Implement** using `sqlite3` with WAL mode and a new connection per operation, so it's safe across threads. Create the spec's `seeds` table on start, and upsert on `seed`. Store seeds in the `TEXT` primary key and timestamps as UTC ISO strings.

- [ ] **Step 4: Run** the same tests. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: add seed store`.

### Task 4: Map rendering and cache

**Files:**
- Create: `app/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `cubiomes.biome_grid`, `weirdness_grid`, `biome_colors`.
- Produces: `render.Layers(cache_dir: str, max_bytes: int = 500 * 1024 * 1024)` with `path(seed: int, layer: str) -> pathlib.Path`, which returns the cached PNG and builds it if needed. `layer` is `"weirdness"` or `"biomes"`. Also `render.weirdness_to_grey(grid: np.ndarray) -> np.ndarray`.

- [ ] **Step 1: Write the failing tests:** `test_png_is_1024_square` for both layers. `test_grey_scale_is_fixed` asserts -1.2 maps to 0, 1.2 maps to 255, 0 maps to 127 or 128, and values outside the range are clipped, so brightness is comparable between seeds (the feasibility test measured about ±1.13). `test_second_call_uses_cache` (same modified time), `test_cache_deletes_oldest_over_limit`, and `test_no_partial_file_left` (a failure during build leaves no file under the final name).

- [ ] **Step 2: Run** `TEST tests/test_render.py`. Expected: FAIL.

- [ ] **Step 3: Implement.** Write to a temp file in the cache folder, then `os.replace`. Biome grids use `biome_colors()`. North is the top of the image: row 0 is the lowest `z`.

- [ ] **Step 4: Run** the same tests. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: add map layers`.

### Task 5: Worker pool and automatic search

**Files:**
- Create: `app/worker.py`, `app/search.py`
- Test: `tests/test_worker.py`, `tests/test_search.py`

**Interfaces:**
- Consumes: `cubiomes.*`, `scoring.evaluate`, `store.Store`.
- Produces:
  - `worker.Scored` dataclass: `seed`, `result`, `spawn`, `spawn_biome`, `structures`.
  - `worker.score_seed(seed: int) -> Scored`: top-level and picklable. Runs in a worker process.
  - `worker.Pool(workers: int = 4)` with `run(fn, *args, timeout: float = 120)`, raising `worker.WorkerCrashed` if the process dies, then replacing the pool.
  - `search.SearchManager(pool, store, scorer=worker.score_seed)` with `start(count: int) -> None` (raises `search.AlreadyRunning`), `stop() -> None`, and `status() -> dict` with `running, tried, target, best_seed, best_score, stopped_early, error`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_worker_crash_is_contained_and_pool_recovers():
    pool = Pool(workers=1)
    with pytest.raises(WorkerCrashed): pool.run(os._exit, 1)
    assert pool.run(score_seed, SEED).seed == SEED

def test_search_saves_only_top_100_and_counts_all(): ...     # count=150, fake scorer
def test_second_search_is_rejected_while_running(): ...
def test_stop_ends_early_and_keeps_best_so_far():            # stopped_early True, rows saved
    ...
def test_saved_rows_exist_before_search_finishes():          # results flushed every 50 seeds
    ...
def test_search_survives_one_crashed_seed(): ...             # tried still reaches target; error noted
def test_search_never_saves_rejected_seeds(): ...
```

- [ ] **Step 2: Run** `TEST tests/test_worker.py tests/test_search.py`. Expected: FAIL.

- [ ] **Step 3: Implement.** Use `ProcessPoolExecutor` with the `spawn` start method. `score_seed` scans the 1:16 grid and builds `WorldFacts`. Seeds come from `secrets.randbits(64)`, converted to signed. Run the search in one background thread with a bounded number of pending tasks (about `2 × workers`), so 100,000 seeds doesn't queue everything. Every 50 tried seeds, save any non-rejected seed in the search's current top 100. A saved seed that later falls out of the top 100 is deleted only if its `source` is `search` and it belongs to the running search, so `store.Store` gains `delete_search_seed(seed: int) -> None`, which never touches `manual` rows, plus a test.

- [ ] **Step 4: Run** the same tests. Expected: PASS.

- [ ] **Step 5: Measure and record** the speed of `count=1000` with 4 workers. The spec's "about a minute" is an estimate, so put the measured figure in the commit message.

- [ ] **Step 6: Commit** with message `feat: add search workers`.

### Task 6: Cloudflare token check

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `auth.AccessVerifier(team_domain: str | None, aud: str | None, jwks_client=None)` with `verify(token: str | None) -> dict`, raising `auth.Denied(status: int, message: str)`.

- [ ] **Step 1: Write the failing tests,** using a locally generated RSA key and a fake key client: valid token passes, and missing, expired, wrong-audience, wrong-issuer and wrongly signed tokens raise `Denied(403)`. Also `test_unset_config_denies` and `test_key_fetch_failure_denies` (`Denied(503)`).

- [ ] **Step 2: Run** `TEST tests/test_auth.py`. Expected: FAIL.

- [ ] **Step 3: Implement** with PyJWT's `PyJWKClient` on `https://<team_domain>/cdn-cgi/access/certs`, RS256 only, checking `aud`, `exp` and `iss` (`https://<team_domain>`).

- [ ] **Step 4: Run** the same tests. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: add Cloudflare Access verification`.

### Task 7: API routes

**Files:**
- Create: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: everything above. Environment: `DATA_DIR` (default `./data`), `CF_TEAM_DOMAIN`, `CF_AUD`.
- Produces: `create_app(pool, store, layers, search, verifier) -> FastAPI` and the module-level `app`. Routes are exactly as in the spec. `POST /api/seeds` takes `{"seed": "<text>"}` and returns the row. `POST /api/seeds` with `{"random": true}` picks a random seed. `POST /api/search` takes `{"count": <int>}`.

- [ ] **Step 1: Write the failing tests** using FastAPI's `TestClient` and a verifier that accepts everything, except in the auth tests:

```python
def test_big_seed_stays_exact_as_string():
    r = client.post("/api/seeds", json={"seed": "9007199254740993"})
    assert r.json()["seed"] == "9007199254740993"
    assert client.get("/api/seeds/9007199254740993").status_code == 200

def test_rejected_seed_keeps_map_and_breakdown():  # fake scorer returns rejected taiga
    ...  # row has rejected_reason and breakdown; both layer PNGs return 200

def test_invalid_seed_is_400_and_not_saved(): ...
def test_seed_above_64_bits_in_url_is_400(): ...
def test_layers_unknown_layer_is_404(): ...
def test_layers_for_unsaved_seed_is_404(): ...
def test_worker_crash_returns_500_with_message(): ...
@pytest.mark.parametrize("count", [0, -1, 100001])
def test_search_count_out_of_range_is_422(count): ...
def test_second_search_is_409(): ...
def test_requests_without_token_are_403(): ...     # includes / and /api/seeds
def test_healthz_needs_no_token(): ...
def test_key_endpoint_failure_returns_503(): ...
```

- [ ] **Step 2: Run** `TEST tests/test_api.py`. Expected: FAIL.

- [ ] **Step 3: Implement.** Enforce auth with middleware reading `Cf-Access-Jwt-Assertion`, exempting only `/healthz`. Seed path values go through strict signed 64-bit integer parsing, never through `seeds.parse`, so a URL can't be treated as a text seed. Run pool and render work in a threadpool so the event loop stays free. Mark any interrupted search as stopped by keeping search status in memory only.

- [ ] **Step 4: Run** the same tests. Expected: PASS.

- [ ] **Step 5: Commit** with message `feat: add API routes`.

### Task 8: The page

**Files:**
- Create: `app/templates/index.html`, `app/static/app.js`, `app/static/app.css`
- Modify: `app/main.py` (serve the page and static files)
- Test: `tests/test_page.py`

**Interfaces:**
- Consumes: the Task 7 routes. `GET /api/seeds/{seed}` also needs its hover data, so add `GET /api/seeds/{seed}/point?x=&z=` returning `{biome, weirdness}`, with a test.

- [ ] **Step 1: Write the failing test** `test_page_has_controls`: `/` returns 200 and contains element ids `seed-input`, `random-btn`, `search-btn`, `search-count`, `stop-btn`, `map`, `biome-opacity`, `seed-list`, `breakdown`.

- [ ] **Step 2: Run** `TEST tests/test_page.py`. Expected: FAIL.

- [ ] **Step 3: Implement the page per the spec's "The page" section.** Stack the two PNGs, plus a canvas for markers. One on/off toggle per structure type, plus 0,0 and spawn markers. Hover calls `/point`, debounced to 150 ms. Keep every seed as a JS string, with no `Number()` or `JSON.parse` reviver. Poll `/api/search` every second while running. Must work on a phone with no horizontal page scroll: the map scales down to the screen width. Light and dark themes through `prefers-color-scheme`.

- [ ] **Step 4: Run** the same test. Expected: PASS.

- [ ] **Step 5: Check in a browser** using a local run with a test-only verifier: enter a seed, toggle overlays, run a search of 50 and stop it, and confirm hovered coordinates match the map at 0,0 and at a corner. Report anything not checked.

- [ ] **Step 6: Commit** with message `feat: add web page`.

### Task 9: Deploy and go live

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `README.md`
- Modify: `~/infra/notes` through `add_note`

- [ ] **Step 1: Write `docker-compose.yml`** per Global Constraints, with `name: seed-finder`, `container_name: seed-finder`, `restart: unless-stopped`, `env_file: .env`, `./data` mounted to `/app/data`, and a `/healthz` healthcheck. Create `.env` with `chmod 600`.

- [ ] **Step 2: Start it.** Confirm port 8103 is still free with `ss -tln`, then run `docker compose up -d --build`. Expected: `curl -s localhost:8103/healthz` returns OK, and `curl -s -o /dev/null -w '%{http_code}' localhost:8103/` returns 403.

- [ ] **Step 3: Back up the `house` tunnel config** to `~/backups/house_tunnel_config_<YYYYMMDD-HHMMSS>.json`. The token is `HF_CF_API_TOKEN` in `~/house-finder/.env`. Read it into a shell variable and never print it.

- [ ] **Step 4: Create the Access app** covering all of `seed-finder.tamairnv.co.uk`, reusing the "FPV owner only" policy. Put its AUD and team domain in `.env`, then run `docker compose up -d`.

- [ ] **Step 5: Add the tunnel route** `http://localhost:8103`, before the `http_status:404` rule and keeping every existing rule. Then add the proxied CNAME `seed-finder` to the `house` tunnel. Diff the config afterwards to confirm only the one rule was added.

- [ ] **Step 6: Verify.** A logged-out `curl -sI https://seed-finder.tamairnv.co.uk/` redirects to `isotopicstudios.cloudflareaccess.com`, and other tunnel sites still respond. Ask Tamair to log in and try it.

- [ ] **Step 7: Run the real-world check with Tamair.** Generate the top 3 seeds on the server's Minecraft version, then compare spawn biome, a nearby village and a rare biome. Report the result either way, and add a version warning to the page if they differ.

- [ ] **Step 8: Record it** with `add_note` under `apps/seed-finder`: folder, port, subdomain, Access app, `.env` names, the cubiomes version limit and the real-world result. Then commit with message `feat: add deployment`.
