"""Configuración pública de Google Maps y del mapa alternativo sin clave."""
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Response

router = APIRouter(prefix="/api/maps")


@router.get("/config")
def map_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return {
            "provider": "google",
            "script_url": "https://maps.googleapis.com/maps/api/js?" + urlencode({
                "key": key, "loading": "async", "v": "weekly", "language": "es", "region": "PE",
            }),
        }
    return {
        "provider": "openstreetmap",
        "tile_url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": '<a href="https://www.openstreetmap.org/copyright">&copy; OpenStreetMap contributors</a>',
        "max_zoom": 19,
    }
