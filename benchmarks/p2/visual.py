"""Experimentos 7 y 8 sobre consultas separadas del corpus indexado."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.multimodal.vector import IVFIndex
from backend.core.multimodal.text import InvertedIndex
from backend.core.multimodal.features import VisualWords
from backend.core.multimodal.paged import FixedArray
from backend.core.storage.disk_counter import DiskCounter
from benchmarks.p2.common import BASE, write_csv, summarize, chart, environment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data/database")
    p.add_argument("--features", default="data/fashion/features")
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    output = BASE / ("smoke-results" if args.quick else "results")
    environment(output)
    root, features = Path(args.data_dir)/"multimodal", Path(args.features)
    info = json.loads((features / "features.json").read_text())
    metadata = json.loads((features / "metadata.json").read_text(encoding="utf-8"))
    n = info["n"]
    queries = min(5, info["queries"]) if args.quick else info["queries"]
    vectors = np.load(features / "embeddings.npy", mmap_mode="r", allow_pickle=False)
    descriptors = np.load(features / "sift.npy", mmap_mode="r", allow_pickle=False)
    offsets = np.load(features / "offsets.npy", allow_pickle=False)
    mapping = FixedArray(root / "dataset_rids.idx", "<Q")
    ids = [r[0] for r in mapping.rows()]
    mapping.close()
    labels = dict(zip(ids, [row["articleType"] for row in metadata[:n]]))
    codebook = VisualWords(root / "codebook.idx")
    visual_rows, ann_rows = [], []
    for q in range(queries):
        query_index = n+q
        label = metadata[query_index]["articleType"]
        truth_index = IVFIndex(root / "ivf")
        truth = {i for i, _ in truth_index.search(vectors[query_index], 10, exact=True)}
        truth_index.close()
        for mode in ("BoVW", "ResNet18+IVF"):
            counter, start = DiskCounter(), time.perf_counter()
            if mode == "BoVW":
                # Extracción SIFT/ResNet medida en prepare_features; aquí cuantización+consulta.
                words = codebook.encode(descriptors[offsets[query_index]:offsets[query_index+1]])
                index = InvertedIndex(root / "bovw", counter)
                result = index.rank(words, 10)
            else:
                index = IVFIndex(root / "ivf", counter)
                result = index.search(vectors[query_index], 10, probes=5)
            index.close()
            visual_rows.append(dict(query=q, category=label, method=mode,
                                    precision5=sum(labels[i] == label for i, _ in result[:5])/5,
                                    precision10=sum(labels[i] == label for i, _ in result[:10])/10,
                                    ms=(time.perf_counter()-start)*1000, reads=counter.disk_reads))
        for probes in (1, 2, 5, 10, 20, 50, 100):
            counter, start = DiskCounter(), time.perf_counter()
            index = IVFIndex(root / "ivf", counter)
            result = index.search(vectors[query_index], 10, probes=probes)
            index.close()
            ann_rows.append(dict(query=q, probes=probes, recall10=len(truth & {i for i, _ in result})/len(truth),
                                 ms=(time.perf_counter()-start)*1000, reads=counter.disk_reads))
        if (q+1)%10 == 0:
            print(f"Exp7/8 consultas: {q+1}/{queries}", flush=True)
    codebook.close()
    write_csv(output / "exp7_raw.csv", visual_rows)
    quality = summarize(visual_rows, ["method"], ["precision5", "precision10", "ms", "reads"])
    for row in quality:
        seconds = info["sift_seconds"] if row["method"] == "BoVW" else info["dense_seconds"]
        row["extraction_ms_per_image"] = seconds*1000/(n+info["queries"])
        row["relevance"] = "same articleType; queries held out"
    write_csv(output / "exp7_quality.csv", quality)
    write_csv(output / "exp8_raw.csv", ann_rows)
    ann = summarize(ann_rows, ["probes"], ["recall10", "ms", "reads"])
    write_csv(output / "exp8_ann.csv", ann)
    chart([{**r, "method": "IVF"} for r in ann], "mean_ms", "mean_recall10", "method", output / "exp8_recall_latency.png", "Latencia media (ms)", "Recall@10", "Calidad vs. latencia · 100 consultas separadas")
    chart([{**r, "method": "IVF"} for r in ann], "probes", "mean_reads", "method", output / "exp8_reads.png", "Probes", "Lecturas de bloques", "Costo de la aproximación")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
    x = np.arange(len(quality))
    ax.bar(x-.17, [r["mean_precision5"] for r in quality], .34, label="Precision@5")
    ax.bar(x+.17, [r["mean_precision10"] for r in quality], .34, label="Precision@10")
    ax.set(xticks=x, xticklabels=[r["method"] for r in quality], ylim=(0,1), ylabel="Precisión", title="BoVW vs. embeddings profundos")
    ax.legend(frameon=False)
    fig.savefig(output / "exp7_quality.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
