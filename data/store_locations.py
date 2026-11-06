"""Ubicaciones sintéticas metropolitanas, restringidas a tierra continental."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

LOCATION_MODEL = "lima-metropolitan-land-v2"
LOCATION_SEED = 2026
LAND_PATH = Path(__file__).parent / "geography/lima_land.geojson"
# Centros y dispersiones de simulación; no son tiendas ni densidades reales.
# Nombre, lon, lat, sigma lon, sigma lat, peso de muestreo.
URBAN_ZONES = (
    ("Ancón", -77.145, -11.775, .018, .020, .7),
    ("Santa Rosa", -77.165, -11.805, .015, .020, .6),
    ("Ventanilla", -77.125, -11.880, .022, .030, 1.2),
    ("Puente Piedra", -77.075, -11.865, .023, .025, 1.4),
    ("Carabayllo", -77.025, -11.865, .026, .030, 1.4),
    ("Comas", -77.045, -11.935, .022, .030, 1.8),
    ("Los Olivos", -77.070, -11.975, .020, .022, 1.4),
    ("Independencia", -77.045, -11.995, .018, .020, 1.0),
    ("San Martín de Porres", -77.085, -12.015, .024, .022, 1.5),
    ("Callao", -77.125, -12.025, .023, .027, 1.4),
    ("Rímac", -77.025, -12.020, .022, .020, 1.0),
    ("San Juan de Lurigancho", -76.990, -11.975, .025, .040, 2.0),
    ("Lima Centro", -77.035, -12.045, .025, .022, 1.5),
    ("San Miguel / Magdalena", -77.080, -12.080, .022, .020, 1.3),
    ("Jesús María / Lince", -77.045, -12.075, .020, .020, 1.0),
    ("San Isidro / Miraflores", -77.030, -12.110, .022, .023, 1.3),
    ("San Borja / Surquillo", -77.005, -12.105, .023, .022, 1.3),
    ("Santa Anita / El Agustino", -76.960, -12.040, .022, .018, 1.2),
    ("Ate", -76.905, -12.035, .035, .022, 1.6),
    ("Huachipa", -76.930, -12.000, .025, .020, 1.0),
    ("La Molina", -76.945, -12.085, .026, .028, 1.3),
    ("Chaclacayo", -76.765, -11.975, .025, .015, .8),
    ("Lurigancho / Chosica", -76.710, -11.940, .025, .020, .8),
    ("Cieneguilla", -76.810, -12.100, .028, .025, .7),
    ("Santiago de Surco", -76.990, -12.145, .027, .028, 1.4),
    ("Chorrillos", -77.000, -12.180, .025, .027, 1.4),
    ("San Juan de Miraflores", -76.970, -12.160, .024, .025, 1.4),
    ("Villa María del Triunfo", -76.940, -12.180, .025, .028, 1.4),
    ("Villa El Salvador", -76.940, -12.225, .026, .027, 1.4),
    ("Pachacámac", -76.875, -12.230, .025, .025, .9),
    ("Lurín", -76.870, -12.275, .025, .025, 1.0),
    ("Punta Hermosa", -76.820, -12.330, .018, .019, .7),
    ("Punta Negra", -76.790, -12.365, .018, .020, .7),
    ("San Bartolo / Santa María", -76.770, -12.400, .016, .020, .7),
    ("Pucusana", -76.770, -12.480, .015, .018, .6),
)


@lru_cache(maxsize=1)
def _land_mask():
    feature = json.loads(LAND_PATH.read_text(encoding="utf-8"))
    geometry = feature["geometry"]
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    result = []
    for polygon in polygons:
        rings = []
        for ring in polygon:
            bands = {}
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                if y1 == y2:
                    continue
                low, high = sorted((y1, y2))
                edge = (x1, y1, (x2-x1)/(y2-y1), low, high)
                for band in range(math.floor(low*100), math.floor(high*100)+1):
                    bands.setdefault(band, []).append(edge)
            rings.append(bands)
        result.append(rings)
    return feature["properties"], result


def _inside_ring(lon, lat, bands):
    crossings = 0
    for x, y, slope, low, high in bands.get(math.floor(lat*100), ()):
        if low <= lat < high and lon < x+(lat-y)*slope:
            crossings += 1
    return bool(crossings % 2)


def sample_store_location(rng):
    for _ in range(10000):
        _, lon, lat, sx, sy, _ = rng.choices(URBAN_ZONES, weights=[z[5] for z in URBAN_ZONES], k=1)[0]
        point = rng.gauss(lon, sx), rng.gauss(lat, sy)
        if is_store_location(*point):
            return point
    raise ValueError("No se pudo generar una ubicación dentro de la máscara terrestre")


def is_store_location(lon, lat):
    if not math.isfinite(lon) or not math.isfinite(lat):
        return False
    return any(_inside_ring(lon, lat, rings[0]) and
               not any(_inside_ring(lon, lat, hole) for hole in rings[1:])
               for rings in _land_mask()[1])


def location_metadata():
    properties, _ = _land_mask()
    return {"model": LOCATION_MODEL, "seed": LOCATION_SEED,
            "region": "Lima Metropolitana y Callao",
            "distribution": "mezcla gaussiana de zonas urbanas; rechazo fuera de tierra continental",
            "coastal_margin_m": properties["coastal_margin_m"],
            "land_mask_sha256": hashlib.sha256(LAND_PATH.read_bytes()).hexdigest(),
            "source_layer": properties["source_layer"],
            "zones": [z[0] for z in URBAN_ZONES]}
