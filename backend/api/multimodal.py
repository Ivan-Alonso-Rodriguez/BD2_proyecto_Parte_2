"""API de recomendación; todas las búsquedas terminan en índices binarios propios."""
from pathlib import Path
import csv
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from .routes import run_operation

router = APIRouter(prefix="/api/multimodal")


class SearchRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    mode: Literal["text", "boolean", "ivf", "exact", "bovw", "spatial", "spatial_knn", "browse"] = "text"
    text: str = Field(default="", max_length=2000)
    k: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1000000)
    category: str | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lat: float | None = Field(default=None, ge=-90, le=90)
    radius: float | None = Field(default=None, ge=0, le=20000)
    reference_id: int | None = None
    probes: int = Field(default=5, ge=1, le=10000)
    vector: list[float] | None = Field(default=None, max_length=768)

    def spec(self):
        conditions = []
        if self.category:
            conditions.append(("categoria", "=", self.category))
        if self.min_price is not None:
            conditions.append(("precio", ">=", self.min_price))
        if self.max_price is not None:
            conditions.append(("precio", "<=", self.max_price))
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("El precio mínimo supera el máximo")
        if any(v is not None for v in (self.lon, self.lat, self.radius)) and not all(v is not None for v in (self.lon, self.lat, self.radius)):
            raise ValueError("Envía lon, lat y radius juntos")
        return dict(mode=self.mode, text=self.text, k=self.k, offset=self.offset, conditions=conditions,
                    radius=(self.lon, self.lat, self.radius) if self.radius is not None else None,
                    reference_id=self.reference_id, probes=self.probes, vector=self.vector)


@router.get("/status")
def status(request: Request):
    def operation(engine):
        mm = engine.multimodal
        return {"ready": mm.ready, **(mm.manifest() if mm.ready else {})}
    return run_operation(request, operation)


@router.post("/search")
def search(body: SearchRequest, request: Request):
    return run_operation(request, lambda engine: engine.multimodal.search(**body.spec()).to_dict())


@router.post("/map")
def map_results(body: SearchRequest, request: Request):
    return run_operation(request, lambda engine: engine.multimodal.search(**body.spec(), all_results=True).to_dict())


@router.post("/image-search")
async def image_search(request: Request, mode: Literal["ivf", "exact", "bovw"] = "ivf", k: int = 12,
                       offset: int = 0,
                       probes: int = 5, category: str | None = None, max_price: float | None = None,
                       lon: float | None = None, lat: float | None = None, radius: float | None = None, text: str = ""):
    size, chunks = 0, []
    async for chunk in request.stream():
        size += len(chunk)
        if size > 10*1024*1024:
            raise HTTPException(413, "La imagen supera 10 MB")
        chunks.append(chunk)
    if not size:
        raise HTTPException(400, "Imagen vacía")
    def operation(engine):
        spec = SearchRequest(mode=mode, text=text, k=k, offset=offset, probes=probes, category=category, max_price=max_price,
                             lon=lon, lat=lat, radius=radius).spec()
        try:
            return engine.multimodal.search(**spec, image=b"".join(chunks)).to_dict()
        except (OSError, SyntaxError) as error:
            raise ValueError("El archivo no es una imagen válida") from error
    return await run_in_threadpool(run_operation, request, operation)


@router.get("/image/{product_id}")
def image(product_id: int, request: Request):
    content = run_operation(request, lambda engine: engine.multimodal.image(product_id))
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/benchmarks")
def benchmarks():
    root = Path(__file__).resolve().parents[2] / "benchmarks/p2/results"
    result = {}
    for name in ("exp5_spatial", "exp5_dimensions", "exp6_build", "exp6_query", "exp7_quality", "exp8_ann"):
        path = root / (name + ".csv")
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as stream:
                result[name] = list(csv.DictReader(stream))
    return result
