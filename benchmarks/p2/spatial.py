"""Experimento 5: 10k/50k/100k, radios y kNN; dimensiones 2..128."""
import argparse
import heapq
import math
import sys
import time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.multimodal.rtree import RTree
from backend.core.multimodal.paged import FixedArray
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.rid import RID
from benchmarks.p2.common import BASE, write_csv, summarize, chart, environment


def measure(root, points, queries, modes, dimension=False):
    n, d = points.shape
    root.mkdir(parents=True, exist_ok=True)
    tree_path, scan_path = root / "tree.idx", root / "points.bin"
    if not tree_path.exists():
        tree = RTree(tree_path, dimensions=d)
        scan = FixedArray(scan_path, f"<Q{d}d")
        scan.write_all((i, *p) for i, p in enumerate(points))
        scan.close()
        for i, point in enumerate(points):
            tree.insert(tuple(point)+tuple(point), RID(i+1, 0))
        tree.close()
    results = []
    for qid, query in enumerate(queries):
        for mode, parameter in modes:
            expected = None
            for method in ("Sequential", "RTree"):
                counter, start = DiskCounter(), time.perf_counter()
                if method == "RTree":
                    tree = RTree(tree_path, counter)
                    try:
                        if mode == "knn":
                            found = [rid.page_id-1 for rid, _ in tree.knn(query, int(parameter))]
                        else:
                            box = tuple(query-parameter)+tuple(query+parameter)
                            candidates = tree.window(box)
                            # Refinamiento exacto desde las páginas de puntos, contado.
                            scan = FixedArray(scan_path, f"<Q{d}d", counter)
                            try:
                                found = [rid.page_id-1 for rid in candidates if math.dist(query, scan.get(rid.page_id-1)[1:]) <= parameter]
                            finally:
                                scan.close()
                    finally:
                        tree.close()
                else:
                    scan = FixedArray(scan_path, f"<Q{d}d", counter)
                    try:
                        if mode == "knn":
                            found = [i for _, i in heapq.nsmallest(int(parameter), ((math.dist(query, row[1:]), row[0]) for row in scan.rows()))]
                        else:
                            found = [row[0] for row in scan.rows() if math.dist(query, row[1:]) <= parameter]
                    finally:
                        scan.close()
                elapsed = (time.perf_counter()-start)*1000
                if expected is None:
                    expected = set(found)
                elif set(found) != expected:
                    raise AssertionError(f"R-Tree difiere del escaneo: {n}/{d}/{qid}/{mode}")
                results.append(dict(n=n, dimensions=d, query=qid, operation=mode, parameter=parameter, method=method,
                                    reads=counter.disk_reads, ms=elapsed, returned=len(found)))
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--queries", type=int, default=12)
    args = p.parse_args()
    output = BASE / ("smoke-results" if args.quick else "results")
    environment(output)
    rng, raw = np.random.default_rng(42), []
    sizes = [1000] if args.quick else [10000, 50000, 100000]
    for n in sizes:
        points = rng.uniform((-77.2, -12.3), (-76.9, -11.95), (n, 2))
        queries = rng.uniform((-77.12, -12.2), (-76.98, -12.05), (args.queries, 2))
        print(f"Exp5 N={n}", flush=True)
        raw.extend(measure(BASE / "work" / f"geo-{n}", points, queries, [("knn", k) for k in (5, 20, 50)] + [("radius", r) for r in (.005, .02, .05)]))
        write_csv(output / "exp5_spatial_raw.csv", raw)
    summary = summarize(raw, ["n", "dimensions", "operation", "parameter", "method"], ["reads", "ms"])
    write_csv(output / "exp5_spatial.csv", summary)
    selected = [{**r, "series": r["method"]+" k="+str(r["parameter"])} for r in summary if r["operation"] == "knn"]
    chart(selected, "n", "mean_reads", "series", output / "exp5_spatial.png", "Puntos N", "Lecturas de bloques", "R-Tree vs. escaneo secuencial", log=True)
    dimensions = [2, 4] if args.quick else [2, 4, 8, 16, 32, 64, 128]
    raw = []
    for d in dimensions:
        n = 200 if args.quick else 2000
        points = rng.random((n, d))
        queries = rng.random((args.queries, d))
        print(f"Exp5 D={d}", flush=True)
        raw.extend(measure(BASE / "work" / f"dimensions-{n}-{d}", points, queries, [("knn", 10)], True))
        write_csv(output / "exp5_dimensions_raw.csv", raw)
    summary = summarize(raw, ["n", "dimensions", "method"], ["reads", "ms"])
    write_csv(output / "exp5_dimensions.csv", summary)
    chart(summary, "dimensions", "mean_ms", "method", output / "exp5_dimensions.png", "Dimensiones D", "Latencia media (ms)", "Dimensionalidad · 2 000 vectores uniformes", log=True)


if __name__ == "__main__":
    main()
