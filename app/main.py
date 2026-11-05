"""FastAPI routes. Everything except /healthz requires a valid Cloudflare Access token."""

import hashlib
import os
import pathlib
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import seeds, worker
from app.auth import AccessVerifier, Denied
from app.render import Layers
from app.search import AlreadyRunning, SearchManager, random_seed
from app.store import Store

MAX_SEARCH = 100_000
PUBLIC_PATHS = {"/healthz"}
HERE = pathlib.Path(__file__).parent
MAP_EDGE = 2048


def _static_version() -> str:
    """Cloudflare caches static files at the edge, so their URLs must change with their content."""
    digest = hashlib.sha256()
    for path in sorted((HERE / "static").iterdir()):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


class SeedIn(BaseModel):
    seed: str | None = None
    random: bool = False


class SearchIn(BaseModel):
    count: int = Field(ge=1, le=MAX_SEARCH)


def create_app(pool, store: Store, layers: Layers, search: SearchManager, verifier,
               scorer=worker.score_seed) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    version = _static_version()

    @app.middleware("http")
    async def require_access(request: Request, call_next):
        if request.url.path not in PUBLIC_PATHS:
            token = request.headers.get("cf-access-jwt-assertion")
            try:
                await run_in_threadpool(verifier.verify, token)
            except Denied as e:
                return JSONResponse({"detail": e.message}, status_code=e.status)
        return await call_next(request)

    @app.exception_handler(seeds.InvalidSeed)
    async def invalid_seed(_: Request, e: seeds.InvalidSeed):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(worker.WorkerCrashed)
    async def crashed(_: Request, e: worker.WorkerCrashed):
        return JSONResponse({"detail": str(e)}, status_code=500)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"v": version})

    @app.post("/api/seeds")
    def add_seed(body: SeedIn):
        if body.random:
            seed, text = random_seed(), None
        else:
            text = body.seed or ""
            seed = seeds.parse(text)
            text = text.strip()
        scored = pool.run(scorer, seed)
        store.save(seed, text, scored.result, scored.spawn, scored.spawn_biome, scored.structures, "manual")
        return store.get(seed)

    @app.get("/api/seeds")
    def list_seeds(sort: Literal["score", "weirdness"] = "score"):
        return store.list(sort)

    def saved_seed(text: str) -> tuple[int, dict]:
        seed = seeds.parse_number(text)
        row = store.get(seed)
        if row is None:
            raise HTTPException(404, "That seed hasn't been scored yet")
        return seed, row

    @app.get("/api/seeds/{seed}")
    def get_seed(seed: str):
        return saved_seed(seed)[1]

    @app.get("/api/seeds/{seed}/layers/{layer}.png")
    def get_layer(seed: str, layer: str):
        number, _ = saved_seed(seed)
        try:
            path = layers.path(number, layer)
        except ValueError:
            raise HTTPException(404, "Unknown map layer") from None
        return FileResponse(path, media_type="image/png")

    @app.get("/api/seeds/{seed}/point")
    def get_point(seed: str, x: int = Query(ge=-MAP_EDGE, lt=MAP_EDGE), z: int = Query(ge=-MAP_EDGE, lt=MAP_EDGE)):
        number, _ = saved_seed(seed)
        return pool.run(worker.point, number, x, z)

    @app.post("/api/search", status_code=202)
    def start_search(body: SearchIn):
        try:
            search.start(body.count)
        except AlreadyRunning as e:
            raise HTTPException(409, str(e)) from None
        return search.status()

    @app.get("/api/search")
    def search_status():
        return search.status()

    @app.post("/api/search/stop")
    def stop_search():
        search.stop()
        return search.status()

    return app


def default_app() -> FastAPI:
    data = pathlib.Path(os.environ.get("DATA_DIR", "./data"))
    data.mkdir(parents=True, exist_ok=True)
    pool = worker.Pool()
    store = Store(str(data / "seeds.db"))
    layers = Layers(str(data / "cache"), run=pool.run)
    verifier = AccessVerifier(os.environ.get("CF_TEAM_DOMAIN"), os.environ.get("CF_AUD"))
    return create_app(pool, store, layers, SearchManager(pool, store), verifier)
