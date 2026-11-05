# Seed Finder design

Date: 2026-11-05. Status: awaiting Tamair's review.

## Goal

Find a Minecraft Java seed worth using for Tamair's server: one with an interesting start, varied biomes and good structures nearby, and that does not spawn players in a spruce forest.

Success means Tamair can open one private web page, press a button, get a ranked list of good seeds, inspect any of them on a map, and see why each one scored as it did.

Tamair is the only user, reaching the site from any device through a Cloudflare login.

## Requirements from Tamair

- Web app at `seed-finder.tamairnv.co.uk`, behind Cloudflare Access.
- Enter a seed, or try random seeds.
- Greyscale weirdness map centred on 0,0.
- Biome and village overlays.
- Keep the seeds that have been run and their scores.
- Java Edition, latest version available.
- Claude chooses how to judge a "cool" seed. Avoiding spruce spawns is the one stated rule.

## Decisions made on Tamair's behalf

- **Runs on the server** (FastAPI calling cubiomes), not WebAssembly in the browser. With a login in front there is no public load to guard against, and the seed list follows Tamair between devices.
- **Automatic search is added.** Trying seeds by hand is slow compared with scoring about 1,000 for you, and the test below shows that is practical.
- **All structures are shown**, not only villages, because structures are part of what makes a seed good.

## Measured feasibility

Throwaway test on TNV-server with cubiomes `e61f905`, 200 random seeds, one thread:

| Step | Time |
|---|---|
| Estimate spawn and read its biome | 2.3 ms per seed |
| Biomes over 4096×4096 blocks at 1:16 | 178 ms per seed |
| Check 9 structure types over the same area | 6.5 ms per seed |
| Weirdness map, 1024×1024 pixels | 100 ms |
| Biome map, 1024×1024 pixels at 1:4 | 3,000 ms |

25 of the 200 seeds (12.5%) spawned in the taiga family. Full scoring costs about 190 ms per seed, so 4 workers should get through 1,000 seeds in about a minute. That figure is scaled up from the single-thread test and has not been measured with 4 workers.

## Scoring

The score is out of 100. Every seed stores its breakdown, and the page displays it. All weights live in one Python file so they are easy to change after seeing real results.

**Automatic rejection** (still recorded when a seed is entered by hand, with the reason shown):

- Spawn biome is `taiga`, `snowy_taiga`, `old_growth_pine_taiga` or `old_growth_spruce_taiga`.
- Spawn biome is any ocean type.

**Scored within 2048 blocks of 0,0:**

| Component | Points | Measures |
|---|---|---|
| Spawn biome | 20 | Top: `cherry_grove`, `meadow`, `mushroom_fields`, `badlands` family. Middle: `plains`, `savanna`, `jungle`, `birch_forest`. Low: everything else allowed. |
| Biome variety | 15 | Number of different surface biomes. |
| Rare biomes | 25 | `mushroom_fields`, `cherry_grove`, `ice_spikes`, `eroded_badlands`, `badlands`, `bamboo_jungle`, `pale_garden`, `jagged_peaks`, `mangrove_swamp`, `old_growth_birch_forest`, with more points for being closer to spawn. |
| Structures | 30 | `Village`, `Trial_Chambers`, `Mansion`, `Monument`, `Ancient_City`, `Desert_Pyramid`, `Jungle_Temple`, `Outpost`, `Trail_Ruins`, with more points for being closer to spawn. Each type's points are capped so many villages cannot dominate. |
| Terrain drama | 10 | Share of the map where peaks-and-valleys, `1 - abs(3*abs(W) - 2)`, is at least 0.7. |

Mean raw weirdness is stored and sortable too, since it was the original idea, but it does not count towards the score. High raw weirdness does not mean dramatic terrain.

Cave biomes (`deep_dark`, `lush_caves`) are not scored in this version because the biome scan reads surface height. Ancient cities still count as structures.

## The page

One page with three areas:

1. **Controls:** seed box (number or text), Random button, and Find Cool Seeds with a seed count (default 1,000, maximum 100,000), progress and Stop.
2. **Map:** 1024×1024 pixels covering 4096×4096 blocks, centred on 0,0. Greyscale weirdness underneath, with a biome layer with adjustable opacity, and structure icons including villages, each of which can be switched on or off. Spawn and 0,0 are marked. Hovering shows coordinates, biome and weirdness.
3. **Ranked list:** seeds sorted by score or mean weirdness. Selecting one opens its map and score breakdown, and the seed can be copied with one click.

## Architecture

```
Browser -> Cloudflare Access -> house tunnel -> FastAPI container on 127.0.0.1:8103
                                                  |-- process pool -> seedlib.so (C) -> cubiomes
                                                  |-- SQLite ./data/seeds.db
                                                  `-- PNG cache ./data/cache
```

| Unit | Job |
|---|---|
| `native/seedlib.c` | Thin C layer over cubiomes: spawn, biome grid, weirdness grid, structure list. No scoring. |
| `app/cubiomes.py` | `ctypes` wrapper that returns plain Python and numpy data. |
| `app/seeds.py` | Converts input to a seed. Text uses Java `String.hashCode`, as the game does. Numbers must fit a signed 64-bit integer. Blank input is rejected. |
| `app/scoring.py` | Pure function from world facts to a score and breakdown. Holds all weights. |
| `app/render.py` | Turns grids into PNG layers with PIL. |
| `app/search.py` | The single background search job, with progress and stop. |
| `app/store.py` | SQLite reads and writes. |
| `app/main.py` | FastAPI routes, Cloudflare JWT check and the Jinja page. |

Cubiomes is cloned at commit `e61f905` during the Docker build. It is MIT licensed.

### Routes

- `GET /` page
- `GET /healthz`
- `POST /api/seeds` score one seed and save it
- `GET /api/seeds?sort=score|weirdness` ranked list
- `GET /api/seeds/{seed}` details, breakdown and structures
- `GET /api/seeds/{seed}/layers/{weirdness|biomes}.png`
- `POST /api/search`, `GET /api/search`, `POST /api/search/stop`

Seeds are sent as JSON strings because JavaScript cannot hold every 64-bit integer exactly.

### Data

`seeds` table: `seed` (primary key, text), `input_text`, `score`, `breakdown` (JSON), `spawn_x`, `spawn_z`, `spawn_biome`, `mean_weirdness`, `rejected_reason`, `structures` (JSON), `source` (`manual` or `search`), `created_at`.

An automatic search counts everything it tries but saves only its top 100 seeds, so the list stays useful. Manually entered seeds are always saved. PNGs can be regenerated, so the cache is capped at 500 MB, deleting the oldest first.

## Failure handling

- **Native crash:** cubiomes runs in worker processes, so a crash fails one task and the web app stays up. The page shows an error.
- **Invalid seed:** a clear message and no database write.
- **Second search while one is running:** rejected, and the page shows the running search.
- **Restart during a search:** seeds already saved remain, and the search shows as stopped.

## Deployment and access

Follows the server conventions: `~/seed-finder`, `openwolf init`, `name`/`container_name: seed-finder`, `restart: unless-stopped`, `127.0.0.1:8103:8000`, runs as uid/gid 1000, `TZ=Europe/London`, `/healthz` with a compose healthcheck, and `read_only`/`tmpfs`/`cap_drop`/`no-new-privileges`. Limited to 4 CPUs and 2 GB of RAM so a search cannot starve other apps. `.env` holds `CF_TEAM_DOMAIN` and `CF_AUD`, with `.env.example` listing the names.

Cloudflare changes, in this order so the site is never exposed without a login:

1. Back up the `house` tunnel config to `~/backups/`.
2. Create an Access app covering all of `seed-finder.tamairnv.co.uk`, reusing the "FPV owner only" policy (Gmail login, 720-hour session).
3. Add the tunnel route to `http://localhost:8103`, before the final catch-all rule.
4. Add the proxied DNS CNAME to the `house` tunnel.
5. Confirm a logged-out request is redirected to the login page.

The app also verifies the `Cf-Access-Jwt-Assertion` token, so it does not rely on the tunnel alone. `/healthz` is exempt for the container healthcheck.

## Known limits

- **Game version:** cubiomes' newest target is `MC_1_21_WD` (1.21 Winter Drop), last updated November 2024. Newer releases may generate worlds differently. This has not been checked.
- **Spawn is an estimate:** this uses `estimateSpawn`, because cubiomes warns that its exact `getSpawn` is slow and can still be inaccurate. A real spawn may land elsewhere, including in a different biome.
- **Structures can be wrong:** cubiomes checks position and biome, but a marked structure may not generate in the real game.
- **Everything is relative to 0,0:** the map and score use 0,0 even when spawn is a few hundred blocks away.

## Testing

- **Unit tests:** seed parsing, including known Java hash values (`"hello"` is `99162322`), and scoring with hand-made world facts, including each rejection rule.
- **Wrapper tests:** the same seed gives identical results twice, and Python grid values match direct C calls to cubiomes at the same coordinates, which catches swapped axes and wrong map scales.
- **Route tests:** the JWT check rejects missing and invalid tokens, and a second search is rejected.
- **Real-world check, needs Tamair or a test server:** generate the top 3 seeds on the server's actual Minecraft version and compare spawn biome, a nearby village and a rare biome with the map. This is the only check that settles the version question, so the result gets reported either way.

## Out of scope for this version

Multi-user accounts, Nether and End maps, a pan-and-zoom infinite map, editing weights from the page, and 3D terrain.
