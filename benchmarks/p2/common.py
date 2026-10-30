import csv
import json
import os
import platform
import statistics
import time
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "benchmarks/p2"
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 140, "axes.grid": True, "grid.alpha": .18, "axes.prop_cycle": plt.cycler(color=["#6554c0", "#20a18b", "#e8a344", "#d65d75"])})


def write_csv(path, rows):
    rows = list(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("No hay mediciones para escribir")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def environment(output):
    import importlib.metadata
    result = {"python": platform.python_version(), "platform": platform.platform(), "cpu": platform.processor(),
              "logical_cpus": os.cpu_count(), "seed": 42, "page_size": 4096,
              "cache": "archivos sin buffering Python; caché del SO no vaciada; objetos índice nuevos por consulta",
              "packages": {name: importlib.metadata.version(name) for name in ("numpy", "torch", "torchvision", "nltk", "opencv-python-headless")}}
    Path(output).mkdir(parents=True, exist_ok=True)
    (Path(output)/"environment.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def summarize(rows, keys, measures):
    groups = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        groups.setdefault(key, []).append(row)
    result = []
    for key, values in groups.items():
        row = dict(zip(keys, key))
        row["queries"] = len(values)
        for field in measures:
            nums = [float(v[field]) for v in values]
            row["mean_"+field] = statistics.mean(nums)
            row["std_"+field] = statistics.pstdev(nums)
        result.append(row)
    return result


def chart(rows, x, y, group, path, xlabel, ylabel, title, log=False):
    fig, axis = plt.subplots(figsize=(8, 4.2), layout="constrained")
    for label in dict.fromkeys(row[group] for row in rows):
        selected = sorted((row for row in rows if row[group] == label), key=lambda row: float(row[x]))
        axis.plot([float(r[x]) for r in selected], [float(r[y]) for r in selected], "o-", label=str(label), markersize=4)
    axis.set(xlabel=xlabel, ylabel=ylabel, title=title)
    if log:
        axis.set_yscale("log")
    axis.legend(frameon=False, fontsize=8)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
