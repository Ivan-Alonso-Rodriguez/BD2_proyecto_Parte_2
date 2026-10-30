"""FastAPI sirve el motor y el cliente estático desde el mismo origen."""

import os
import threading
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from backend.api.routes import router
from backend.api.multimodal import router as multimodal_router
from backend.core.query_engine.executor import QueryExecutor

ROOT = Path(__file__).resolve().parents[1]


def create_app(directory=None, page_size=4096):
    app = FastAPI(title="Atlas · Motor multimodal", version="2.0")
    app.state.engine = QueryExecutor(
        directory=directory
        or os.environ.get("BD2_DATA_DIR", str(ROOT / "data/database")),
        page_size=page_size,
    )
    app.state.engine_lock = threading.RLock()
    app.include_router(router)
    app.include_router(multimodal_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "bd2-relacional"}

    app.mount("/experiments", StaticFiles(directory=ROOT / "benchmarks/p2/results", check_dir=False), name="experiments")
    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    return app


app = create_app()
