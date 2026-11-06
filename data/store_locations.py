"""Ubicaciones sintéticas en sectores interiores de Lima, alejados de la costa."""

LOCATION_MODEL = "lima-inland-v1"
LOCATION_SEED = 2026
# Ventanas conservadoras de referencia; no son límites administrativos.
# Orden: longitud mínima, latitud mínima, longitud máxima, latitud máxima.
STORE_AREAS = (
    (-77.040, -12.105, -77.025, -12.080),  # entorno Lince / San Isidro
    (-77.020, -12.115, -77.005, -12.095),  # entorno Surquillo
    (-77.010, -12.105, -76.990, -12.085),  # entorno San Borja
    (-76.995, -12.130, -76.975, -12.110),  # entorno Santiago de Surco
)


def sample_store_location(rng):
    west, south, east, north = rng.choice(STORE_AREAS)
    return rng.uniform(west, east), rng.uniform(south, north)


def is_store_location(lon, lat):
    return any(west <= lon <= east and south <= lat <= north
               for west, south, east, north in STORE_AREAS)


def location_metadata():
    return {"model": LOCATION_MODEL, "seed": LOCATION_SEED,
            "region": "sectores urbanos interiores de Lima",
            "areas": [list(area) for area in STORE_AREAS]}
