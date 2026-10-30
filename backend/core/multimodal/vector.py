"""IVF Flat y k-NN exacto propios. Sin FAISS, HNSWlib ni motores externos."""
import heapq
import math
import struct
from pathlib import Path
import numpy as np
from backend.core.storage.disk_manager import DiskManager
from .paged import PAGE_SIZE, FixedArray

LIST_HEADER = struct.Struct("<4sIIi")


def normalized(vectors):
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def kmeans(vectors, clusters, iterations=15, seed=42, spherical=False):
    """Lloyd por lotes; K-Means solo para entrenamiento, nunca para almacenar índices."""
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or not len(vectors) or not np.isfinite(vectors).all():
        raise ValueError("Matriz de entrenamiento inválida")
    clusters = min(max(1, int(clusters)), len(vectors))
    rng = np.random.default_rng(seed)
    centers = vectors[rng.choice(len(vectors), clusters, replace=False)].copy()
    for _ in range(iterations):
        sums = np.zeros_like(centers)
        counts = np.zeros(clusters, dtype=np.int64)
        for start in range(0, len(vectors), 512):
            batch = vectors[start:start+512]
            labels = nearest(batch, centers)
            np.add.at(sums, labels, batch)
            np.add.at(counts, labels, 1)
        new = sums / np.maximum(counts[:, None], 1)
        for i in np.flatnonzero(counts == 0):
            new[i] = vectors[rng.integers(len(vectors))]
        new = normalized(new) if spherical else new.astype(np.float32)
        if np.allclose(centers, new, atol=1e-5):
            break
        centers = new
    return centers.astype(np.float32)


def nearest(vectors, centers):
    distance = (vectors*vectors).sum(1)[:, None] + (centers*centers).sum(1)[None, :] - 2*vectors@centers.T
    return np.argmin(distance, axis=1)


def distance(vector, query, metric):
    if metric == "COSINE":
        nv, nq = np.linalg.norm(vector), np.linalg.norm(query)
        # Convención explícita: cualquier vector cero tiene distancia coseno 1.
        return float(np.clip(1-np.dot(vector, query)/(nv*nq), 0, 2)) if nv and nq else 1.
    return float(np.linalg.norm(vector-query))


class IVFIndex:
    def __init__(self, directory, counter=None):
        root = Path(directory)
        self.lists = DiskManager(root / "lists.ivf", counter=counter)
        raw = self.lists.read_page(0)
        magic, self.d, self.n, code = struct.unpack_from("<4sIQI", raw)
        if magic != b"IVF2":
            self.close()
            raise ValueError("IVF incompatible")
        self.metric = "COSINE" if code == 1 else "L2"
        self.centroids = FixedArray(root / "centroids.dir", f"<I{self.d}fiI", counter)
        self.exact = FixedArray(root / "vectors.vec", f"<Q{self.d}f", counter)
        self.entry = struct.Struct(f"<Q{self.d}f")
        self.capacity = (PAGE_SIZE-LIST_HEADER.size)//self.entry.size
        self.last_candidates = 0

    @classmethod
    def build(cls, directory, ids, vectors, clusters=None, metric="COSINE", counter=None, seed=42):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ValueError("El directorio IVF debe estar vacío")
        vectors = np.asarray(vectors, dtype=np.float32)
        ids = list(ids)
        if vectors.ndim != 2 or len(vectors) != len(ids) or not len(ids) or len(set(ids)) != len(ids) or not np.isfinite(vectors).all():
            raise ValueError("IDs o vectores inválidos")
        if not 1 <= vectors.shape[1] <= 768 or metric not in ("COSINE", "L2"):
            raise ValueError("Dimensión o métrica no soportada")
        if metric == "COSINE":
            vectors = normalized(vectors)
        n, d = vectors.shape
        clusters = clusters or math.isqrt(n)
        sample = np.random.default_rng(seed).choice(n, min(n, 10000), replace=False)
        centers = kmeans(vectors[sample], clusters, seed=seed, spherical=metric == "COSINE")
        assignments = np.concatenate([nearest(vectors[s:s+512], centers) for s in range(0, n, 512)])
        lists = DiskManager(root / "lists.ivf", counter=counter)
        centroids = FixedArray(root / "centroids.dir", f"<I{d}fiI", counter)
        exact = FixedArray(root / "vectors.vec", f"<Q{d}f", counter)
        entry = struct.Struct(f"<Q{d}f")
        capacity = (PAGE_SIZE-LIST_HEADER.size)//entry.size
        try:
            lists.allocate_page(struct.pack("<4sIQI", b"IVF2", d, n, metric == "COSINE").ljust(PAGE_SIZE, b"\0"))
            directory_rows = []
            for cluster, center in enumerate(centers):
                members = np.flatnonzero(assignments == cluster)
                head = lists.num_pages() if len(members) else -1
                directory_rows.append((cluster, *center, head, len(members)))
                for start in range(0, len(members), capacity):
                    batch = members[start:start+capacity]
                    page = lists.num_pages()
                    nxt = page+1 if start+capacity < len(members) else -1
                    raw = bytearray(PAGE_SIZE)
                    LIST_HEADER.pack_into(raw, 0, b"IVL2", page, len(batch), nxt)
                    for j, idx in enumerate(batch):
                        entry.pack_into(raw, LIST_HEADER.size+j*entry.size, ids[idx], *vectors[idx])
                    lists.allocate_page(bytes(raw))
            centroids.write_all(directory_rows)
            exact.write_all((ids[i], *vectors[i]) for i in sorted(range(n), key=lambda i: ids[i]))
        finally:
            lists.close()
            centroids.close()
            exact.close()
        return cls(root, counter)

    def _validate(self, query, k):
        query = np.asarray(query, dtype=np.float32)
        if query.shape != (self.d,) or not np.isfinite(query).all() or k < 1:
            raise ValueError(f"Se requiere un vector finito de {self.d} dimensiones y k positivo")
        return normalized(query) if self.metric == "COSINE" else query

    def search(self, query, k=10, probes=5, allowed=None, exact=False, radius=None, exclude=None):
        query = self._validate(query, k)
        if probes < 1 or (radius is not None and (not math.isfinite(radius) or radius < 0)):
            raise ValueError("probes/radio inválido")
        best, self.last_candidates = [], 0
        def candidates():
            if exact:
                yield from self.exact.rows()
                return
            directory = list(self.centroids.rows())  # C << N; solo el directorio de centroides.
            order = sorted(directory, key=lambda row: (distance(np.array(row[1:1+self.d], dtype=np.float32), query, self.metric), row[0]))
            for row in order[:probes]:
                page, remaining = row[-2:]
                while page != -1:
                    raw = self.lists.read_page(page)
                    magic, actual, count, nxt = LIST_HEADER.unpack_from(raw)
                    if magic != b"IVL2" or actual != page or not 1 <= count <= self.capacity or count > remaining:
                        raise ValueError("Lista IVF corrupta")
                    remaining -= count
                    for j in range(count):
                        yield self.entry.unpack_from(raw, LIST_HEADER.size+j*self.entry.size)
                    page = nxt
                if remaining:
                    raise ValueError("Lista IVF truncada")
        for row in candidates():
            doc_id = row[0]
            self.last_candidates += 1
            if doc_id == exclude or (allowed is not None and doc_id not in allowed):
                continue
            dist = distance(np.asarray(row[1:], dtype=np.float32), query, self.metric)
            if radius is not None and dist > radius:
                continue
            item = (-dist, -doc_id)
            if len(best) < k:
                heapq.heappush(best, item)
            elif item > best[0]:
                heapq.heapreplace(best, item)
        return [(-doc_id, -dist) for dist, doc_id in sorted(best, reverse=True)]

    def vector(self, doc_id):
        row = self.exact.find(doc_id)
        if row is None:
            raise ValueError("Vector no encontrado")
        return np.asarray(row[1:], dtype=np.float32)

    def close(self):
        self.lists.close()
        if hasattr(self, "centroids"):
            self.centroids.close()
            self.exact.close()
