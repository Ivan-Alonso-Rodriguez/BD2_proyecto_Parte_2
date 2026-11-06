"""Prepara la máscara terrestre de Lima/Callao desde INEI/MINAM (solo offline).

Requiere Shapely para preparar el recurso; la aplicación no depende de Shapely.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely import make_valid
from shapely.affinity import scale
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

SOURCE_LAYER = "https://geoservidorperu.minam.gob.pe/arcgis/rest/services/GEOLOMAS_final/MapServer/0"
SOURCE_URL = SOURCE_LAYER + "/query?" + urlencode({
    "where": "1=1", "outFields": "IDDIST,NOMBDIST", "outSR": "4326",
    "f": "geojson", "geometryPrecision": "6",
})
MARGIN_METERS = 350


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="GeoJSON original ya descargado")
    parser.add_argument("--output", type=Path, default=Path("data/geography/lima_land.geojson"))
    args = parser.parse_args()
    if args.source:
        raw = args.source.read_bytes()
    else:
        with urlopen(Request(SOURCE_URL, headers={"User-Agent": "Atlas-BD2-academic/2.0"}), timeout=90) as response:
            raw = response.read()
    source = json.loads(raw)
    polygons = [make_valid(shape(feature["geometry"])) for feature in source["features"]]
    land = unary_union(polygons)
    # Excluir islotes: el catálogo representa tiendas en la masa continental.
    if land.geom_type == "MultiPolygon":
        land = max(land.geoms, key=lambda polygon: polygon.area)
    # Aproximación métrica local suficiente para un margen conservador de 350 m.
    mx, my = 111320 * math.cos(math.radians(12)), 110574
    metric = scale(land, xfact=mx, yfact=my, origin=(0, 0)).buffer(-MARGIN_METERS)
    safe_land = scale(metric, xfact=1/mx, yfact=1/my, origin=(0, 0)).simplify(.00004, preserve_topology=True)
    if safe_land.is_empty or not safe_land.is_valid:
        raise ValueError("La máscara terrestre no es válida")
    geometry = mapping(safe_land)

    def rounded(value):
        return round(value, 7) if isinstance(value, (float, int)) else [rounded(v) for v in value]

    geometry["coordinates"] = rounded(geometry["coordinates"])
    result = {"type": "Feature", "properties": {
        "name": "Lima Metropolitana y Callao: tierra continental con margen interior",
        "source": "Límites distritales INEI 2017 publicados por MINAM",
        "source_layer": SOURCE_LAYER, "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "districts": len(source["features"]), "coastal_margin_m": MARGIN_METERS,
        "simplification_degrees": .00004,
        "note": "Máscara de referencia para ubicaciones sintéticas; no delimita predios ni tiendas reales.",
    }, "geometry": geometry}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size,
                      "geometry": safe_land.geom_type, "bounds": safe_land.bounds}))


if __name__ == "__main__":
    main()
