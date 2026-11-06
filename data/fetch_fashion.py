"""Descarga un shard público (22 036 productos); no requiere cuenta ni API key."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen, Request
import pyarrow.parquet as pq

DATASET = "ashraq/fashion-product-images-small"
SHARD = "data/train-00000-of-00002-6cff4c59f91661c3.parquet"


def validate_parquet(path):
    if pq.read_metadata(path).num_rows == 0:
        raise ValueError("El dataset Parquet no contiene productos")


def validate_cache(target, source_path):
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict) or target.stat().st_size != source.get("bytes"):
        raise ValueError("El tamaño del dataset no coincide con source.json")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != source.get("sha256"):
        raise ValueError("El SHA-256 del dataset no coincide con source.json")
    validate_parquet(target)


def download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest, size = hashlib.sha256(), 0
    with urlopen(Request(url, headers={"User-Agent": "Atlas-BD2-academic/2.0"}), timeout=120) as response, temporary.open("wb") as output:
        while chunk := response.read(1024*1024):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        expected = response.headers.get("Content-Length")
        if expected is not None and size != int(expected):
            raise ValueError(f"Descarga incompleta: {size} de {expected} bytes")
        output.flush()
        os.fsync(output.fileno())
    validate_parquet(temporary)
    temporary.replace(destination)
    return {"url": url, "bytes": size, "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/fashion")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "fashion.parquet"
    source_path = root / "source.json"
    if target.exists():
        try:
            validate_cache(target, source_path)
        except (OSError, ValueError, TypeError) as error:
            print(f"Caché inválido: {error}. Se descargará nuevamente.", flush=True)
        else:
            print(f"Se conserva {target}; tamaño, SHA-256 y Parquet verificados.")
            return
    with urlopen(f"https://huggingface.co/api/datasets/{DATASET}", timeout=60) as response:
        revision = json.load(response)["sha"]
    source = download(f"https://huggingface.co/datasets/{DATASET}/resolve/{revision}/{SHARD}", target)
    source.update(dataset=DATASET, revision=revision, original_source="https://www.kaggle.com/datasets/paramaggarwal/fashion-product-images-small")
    temporary_source = source_path.with_suffix(".json.tmp")
    temporary_source.write_text(json.dumps(source, indent=2), encoding="utf-8")
    temporary_source.replace(source_path)
    print(json.dumps(source, indent=2))


if __name__ == "__main__":
    main()
