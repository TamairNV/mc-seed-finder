# Seed Finder

Scores Minecraft Java Edition seeds, maps them, and searches for good ones. It was built to pick a world for a friends' server, and runs at `seed-finder.tamairnv.co.uk` behind a login.

## Features

- **Score any seed:** enter one, or try a random one, and see why it scored as it did.
- **Background search:** tries random seeds and keeps the best 100. Only admins can start or stop it.
- **Maps centred on 0,0:** weirdness, surface biomes, underground biomes and height, at 1000, 2000 or 6144 blocks across.
- **Saved results:** every seed you run is kept with its score, and you can shortlist the ones you like.

## How seeds are scored

All weights are at the top of `app/scoring.py`.

| Factor | What earns points |
|---|---|
| Biome variety (up to 40) | How many biomes there are near spawn, and how evenly they mix |
| Rare biomes (up to 25) | Mushroom fields, cherry groves, ice spikes and similar, close to spawn |
| Structures | Villages, trial chambers, mansions, ancient cities and others within 2048 blocks |
| Terrain (up to 10) | A good share of peaks and valleys |
| Spawn biome (up to 5) | Spawning somewhere interesting, such as a cherry grove or a meadow |

A seed is rejected outright if it spawns in a spruce biome or an ocean.

## How it works

World generation uses [cubiomes](https://github.com/Cubitect/cubiomes), a C library compiled into `seedlib.so` during the Docker build. It's pinned to commit `e61f905`, whose newest target is the 1.21 Winter Drop, so **check any seed in your real game version before relying on it**.

The stack is FastAPI, numpy and Pillow, with results stored in SQLite. Cubiomes runs in separate worker processes, so a crash in native code can't take down the web app.

Every page and API route needs a valid Cloudflare Access token, and access fails closed if that isn't set up. Roles come from a separate access panel service, reached over the `access-net` Docker network. `/healthz` is the exception.

## Run it locally

Needs Docker with Compose.

```sh
cp .env.example .env
docker network create access-net
mkdir -p data
docker compose up -d --build
```

It listens on `127.0.0.1:8103`. Without Cloudflare Access in front, pages refuse the request, so the tests are the easiest way to try changes locally:

```sh
docker build -q --target test -t seed-finder-test .
docker run --rm seed-finder-test pytest
```

| Setting in `.env` | What it's for |
|---|---|
| `CF_TEAM_DOMAIN` | Cloudflare Access team domain |
| `CF_AUD` | Audience tag of the Access application |
| `ACCESS_SITE` | This site's name in the access panel |
| `ACCESS_LOWEST_ROLE` | Role used only while the panel can't be reached |

## Deployment

| | |
|---|---|
| Folder | `~/seed-finder` |
| Port | `127.0.0.1:8103` |
| Address | `seed-finder.tamairnv.co.uk` |
| Data | `data/seeds.db` |

To update it, run `docker compose up -d --build` in the folder.

## Project layout

```
app/main.py      Routes
app/scoring.py   Score weights and rules
app/search.py    The background search
app/worker.py    Runs cubiomes in separate processes
app/cubiomes.py  Python bindings for the native library
app/render.py    Map layers
app/store.py     SQLite storage
app/auth.py      Cloudflare Access checks
native/seedlib.c C wrapper around cubiomes
tests/           Test suite
```
