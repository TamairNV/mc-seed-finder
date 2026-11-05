# Seed Finder

Scores Minecraft Java seeds, maps them, and searches for good ones. Private, at `seed-finder.tamairnv.co.uk` behind Cloudflare Access.

- Run: `docker compose up -d --build` (needs `.env`, see `.env.example`). Listens on `127.0.0.1:8103`.
- Test: `docker build -q --target test -t seed-finder-test . && docker run --rm seed-finder-test pytest`
- Scoring weights: `app/scoring.py`.
- World generation: cubiomes `e61f905`, whose newest target is the 1.21 Winter Drop. Check seeds in the real game version.
