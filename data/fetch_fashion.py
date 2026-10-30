"""Descarga un shard público (22 036 productos); no requiere cuenta ni API key."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen, Request

DATASET = "ashraq/fashion-product-images-small"
SHARD = "data/train-00000-of-00002-6cff4c59f91661c3.parquet"


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
    temporary.replace(destination)
    return {"url": url, "bytes": size, "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/fashion")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "fashion.parquet"
    if target.exists():
        print(f"Se conserva {target}; para una nueva descarga elige otro directorio.")
        return
    with urlopen(f"https://huggingface.co/api/datasets/{DATASET}", timeout=60) as response:
        revision = json.load(response)["sha"]
    source = download(f"https://huggingface.co/datasets/{DATASET}/resolve/{revision}/{SHARD}", target)
    source.update(dataset=DATASET, revision=revision, original_source="https://www.kaggle.com/datasets/paramaggarwal/fashion-product-images-small")
    (root / "source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    print(json.dumps(source, indent=2))


if __name__ == "__main__":
    main()
