"""Importa productos reales mediante Heap/B+/Hash de P1 y construye índices P2."""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.prepare_features import rows
from backend.core.query_engine.executor import QueryExecutor
from backend.core.catalog.table_storage import TableStorage
from backend.core.storage.disk_counter import DiskCounter
from backend.core.multimodal.paged import BlobStore, pack_rid, FixedArray
from backend.core.multimodal.rtree import RTree
from backend.core.multimodal.text import InvertedIndex
from backend.core.multimodal.vector import IVFIndex
from backend.core.multimodal.features import VisualWords


def description(row):
    fields = [row.get(k) or "" for k in ("productDisplayName", "gender", "masterCategory", "subCategory", "articleType", "baseColour", "season", "usage")]
    translations = {"Footwear": "calzado zapatos zapatillas", "Apparel": "ropa prendas", "Accessories": "accesorios", "Personal Care": "cuidado personal"}
    fields.append(translations.get(row.get("masterCategory"), ""))
    return " ".join(str(v) for v in fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/database")
    parser.add_argument("--features", default="data/fashion/features")
    parser.add_argument("--source", default="data/fashion/fashion.parquet")
    parser.add_argument("--words", type=int, default=128)
    args = parser.parse_args()
    directory, features = Path(args.data_dir), Path(args.features)
    root = directory / "multimodal"
    if (root / "manifest.json").exists():
        print("Colección existente conservada. Usa otro --data-dir para reconstruir.")
        return
    info = json.loads((features / "features.json").read_text())
    n = info["n"]
    vectors = np.load(features / "embeddings.npy", mmap_mode="r", allow_pickle=False)
    descriptors = np.load(features / "sift.npy", mmap_mode="r", allow_pickle=False)
    offsets = np.load(features / "offsets.npy", allow_pickle=False)
    engine = QueryExecutor(directory=directory)
    engine.execute("CREATE TABLE productos (id INT PRIMARY KEY, titulo CHAR(180), cuerpo CHAR(512), categoria CHAR(48), precio FLOAT, lon FLOAT, lat FLOAT, imagen INT) USING HEAP;")
    engine.execute("CREATE INDEX precio_btree ON productos(precio) USING BTREE;")
    engine.execute("CREATE INDEX categoria_hash ON productos(categoria) USING HASH;")
    root.mkdir(parents=True, exist_ok=True)
    counter, rng, start = DiskCounter(), random.Random(2026), time.perf_counter()
    geo = RTree(root / "geo.idx", counter)
    blobs = BlobStore(root / "images.blobs", counter)
    ids, documents, categories = [], [], set()
    table = engine.schema_manager.get_table("productos")
    with TableStorage(engine.schema_manager, table, counter) as storage:
        for i, row in enumerate(rows(args.source, n)):
            # Ubicaciones y precios sintéticos: no los provee el dataset original.
            lon, lat = -77.04+rng.gauss(0, .065), -12.10+rng.gauss(0, .055)
            price = round(rng.uniform(25, 500), 2)
            body = description(row)
            category = row["masterCategory"] or "Other"
            categories.add(category)
            image_page = blobs.append(row["image"]["bytes"])
            rid = storage.insert([int(row["id"]), row["productDisplayName"] or "Producto", body, category, price, lon, lat, image_page])
            ids.append(pack_rid(rid))
            documents.append((pack_rid(rid), body))
            geo.insert((lon, lat, lon, lat), rid)
            if (i+1)%2000 == 0:
                print(f"Heap + B+ + Hash + R-Tree + blobs: {i+1}/{n}", flush=True)
    geo.close()
    blobs.close()
    print("Construyendo vocabulario textual...", flush=True)
    InvertedIndex.build(root / "text", documents, counter).close()
    sample_rng = np.random.default_rng(42)
    sample = sample_rng.choice(int(offsets[n]), min(30000, int(offsets[n])), replace=False)
    print("Entrenando codebook SIFT...", flush=True)
    visual = VisualWords.train(root / "codebook.idx", descriptors[sample], args.words, counter)
    visual_docs = ((ids[i], visual.encode(descriptors[offsets[i]:offsets[i+1]])) for i in range(n))
    InvertedIndex.build(root / "bovw", visual_docs, counter).close()
    visual.close()
    print("Construyendo IVF sobre embeddings ResNet-18...", flush=True)
    IVFIndex.build(root / "ivf", ids, vectors[:n], clusters=math.isqrt(n), counter=counter).close()
    # Mapa estable posición del dataset -> RID, solo para evaluación fuera de línea.
    mapping = FixedArray(root / "dataset_rids.idx", "<Q", counter)
    mapping.write_all((rid,) for rid in ids)
    mapping.close()
    manifest = {"version": 2, "table": "productos", "n": n, "dimensions": 512, "clusters": math.isqrt(n),
                "visual_words": args.words, "categories": sorted(categories), "model": info["model"],
                "metadata_synthetic": ["precio", "lon", "lat"], "text_description": "concatenación de atributos originales y etiquetas de categoría en español",
                "source": json.loads((Path(args.source).parent / "source.json").read_text()),
                "build_seconds": time.perf_counter()-start, "build_io": counter.snapshot(),
                "indexes": {"geo": {"kind": "RTREE", "column": "ubicacion"}, "text": {"kind": "INVERTED", "column": "cuerpo"}, "ivf": {"kind": "IVF", "column": "embedding"}}}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("n", "build_seconds", "build_io")}, indent=2))


if __name__ == "__main__":
    main()
