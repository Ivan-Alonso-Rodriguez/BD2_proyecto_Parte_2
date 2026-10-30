"""Extracción offline reproducible. El caché .npy no es un índice del motor."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core.multimodal.features import ResNetEncoder, sift


def rows(path, limit=None):
    count = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=128):
        for row in batch.to_pylist():
            if limit is not None and count >= limit:
                return
            count += 1
            yield row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10000)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--source", default="data/fashion/fashion.parquet")
    parser.add_argument("--output", default="data/fashion/features")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    if (root / "features.json").exists():
        info = json.loads((root / "features.json").read_text())
        if info["n"] != args.n or info["queries"] != args.queries:
            raise ValueError("El caché tiene otra configuración; usa --output nuevo")
        print("Se conservan las características ya extraídas.")
        return
    encoder = ResNetEncoder(cache=ROOT / ".cache/torch")
    vectors, descriptions, offsets, metadata = [], [], [0], []
    dense_seconds, sift_seconds = 0., 0.
    iterator = iter(rows(args.source, args.n+args.queries))
    while True:
        batch = []
        for _ in range(32):
            try:
                batch.append(next(iterator))
            except StopIteration:
                break
        if not batch:
            break
        images = [row["image"]["bytes"] for row in batch]
        start = time.perf_counter()
        vectors.extend(encoder.encode(images))
        dense_seconds += time.perf_counter()-start
        start = time.perf_counter()
        for row, image in zip(batch, images):
            descriptors = sift(image)
            descriptions.extend(descriptors)
            offsets.append(len(descriptions))
            metadata.append({key: value for key, value in row.items() if key != "image"})
        sift_seconds += time.perf_counter()-start
        if len(vectors) % 512 == 0:
            print(f"Extracción: {len(vectors)}/{args.n+args.queries}", flush=True)
    if len(vectors) != args.n+args.queries:
        raise ValueError("El origen no contiene suficientes productos")
    np.save(root / "embeddings.npy", np.asarray(vectors, dtype=np.float32), allow_pickle=False)
    np.save(root / "sift.npy", np.asarray(descriptions, dtype=np.float32), allow_pickle=False)
    np.save(root / "offsets.npy", np.asarray(offsets, dtype=np.int64), allow_pickle=False)
    (root / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    info = {"n": args.n, "queries": args.queries, "model": "ResNet18_IMAGENET1K_V1", "dimensions": 512,
            "sift_seconds": sift_seconds, "dense_seconds": dense_seconds, "query_partition": "siguientes filas, no indexadas",
            "sift_resize": [224, 224], "batch_size": 32, "threads": 4}
    (root / "features.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
