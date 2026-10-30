import math
import random
from collections import Counter
import numpy as np
import pytest
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.rid import RID
from backend.core.multimodal.paged import BlobStore, FixedArray, pack_rid, unpack_rid
from backend.core.multimodal.rtree import RTree, mindist
from backend.core.multimodal.text import InvertedIndex, Analyzer, merge
from backend.core.multimodal.vector import IVFIndex, distance


def test_fixed_array_crosses_pages_and_reopens(tmp_path):
    counter = DiskCounter()
    array = FixedArray(tmp_path / "array.idx", "<Qd", counter)
    array.write_all((i, i/3) for i in range(2000))
    array.close()
    array = FixedArray(tmp_path / "array.idx", "<Qd", counter)
    counter.reset()
    assert array.find(1999) == (1999, 1999/3)
    assert 0 < counter.disk_reads < 9
    assert len(list(array.rows())) == 2000
    assert array.find(3000) is None
    array.close()


def test_blob_round_trip(tmp_path):
    blobs = BlobStore(tmp_path / "images.blobs")
    content = bytes(range(256))*100
    first = blobs.append(content)
    second = blobs.append(b"other")
    blobs.close()
    blobs = BlobStore(tmp_path / "images.blobs")
    assert blobs.get(first) == content
    assert blobs.get(second) == b"other"
    assert blobs.disk.filepath.stat().st_size % 4096 == 0
    blobs.close()


@pytest.mark.parametrize("dimensions", [2, 4, 16, 128])
def test_rtree_recursive_splits_reopen_knn_and_window(tmp_path, dimensions):
    rng = random.Random(42)
    points = [tuple(rng.random() for _ in range(dimensions)) for _ in range(180)]
    path = tmp_path / "spatial.idx"
    tree = RTree(path, dimensions=dimensions, max_entries=5)
    for i, point in enumerate(points):
        tree.insert(point+point, RID(i+1, 0))
    assert tree.root != 1
    tree.close()
    tree = RTree(path)
    q = (.47,)*dimensions
    expected = sorted(range(len(points)), key=lambda i: (math.dist(points[i], q), i))[:20]
    result = tree.knn(q, 20)
    assert [rid.page_id-1 for rid, _ in result] == expected
    box = (.2,)*dimensions + (.8,)*dimensions
    assert {rid.page_id-1 for rid in tree.window(box)} == {i for i, p in enumerate(points) if all(.2 <= v <= .8 for v in p)}
    tree.close()


def test_rtree_duplicate_points_and_rectangles(tmp_path):
    tree = RTree(tmp_path / "geo.idx", max_entries=4)
    for i in range(50):
        tree.insert((1, 1, 2, 3), RID(i+1, 0))
    assert len(tree.window((1.5, 1.5, 1.6, 1.6))) == 50
    assert [rid.page_id for rid, _ in tree.knn((1.5, 2), 3)] == [1, 2, 3]
    with pytest.raises(ValueError):
        tree.insert((2, 2, 1, 1), RID(51, 0))
    tree.close()


@pytest.mark.parametrize("operation", ["AND", "OR", "NOT"])
def test_linear_merge_against_set_oracle(operation):
    rng = random.Random(3)
    for _ in range(50):
        a, b = sorted(rng.sample(range(100), 30)), sorted(rng.sample(range(100), 20))
        expected = {"AND": set(a)&set(b), "OR": set(a)|set(b), "NOT": set(a)-set(b)}[operation]
        assert merge(a, b, operation) == sorted(expected)


def test_inverted_boolean_ranking_and_persistence(tmp_path):
    texts = {1: "red red blue shoes", 2: "blue cotton shirt", 3: "red leather shoes", 4: "cotton watch", 5: ""}
    index = InvertedIndex.build(tmp_path / "text", texts.items())
    index.close()
    index = InvertedIndex(tmp_path / "text")
    assert index.boolean("red AND shoes") == [1, 3]
    assert index.boolean("red OR cotton AND shirt") == [1, 2, 3]
    assert index.boolean("(red OR cotton) AND NOT leather") == [1, 2, 4]
    assert index.boolean("red AND-NOT blue") == [3]
    assert index.boolean("NOT red") == [2, 4, 5]
    assert index.boolean("nonexistent") == []
    with pytest.raises(ValueError):
        index.boolean("red OR")
    analyzer = Analyzer()
    counts = {i: Counter(analyzer.tokens(t)) for i, t in texts.items()}
    vocabulary = set().union(*(set(c) for c in counts.values()))
    idf = {t: math.log10(len(texts)/sum(t in c for c in counts.values())) for t in vocabulary}
    query = Counter(analyzer.tokens("red shoes"))
    qv = {t: (1+math.log10(tf))*idf[t] for t, tf in query.items()}
    expected = []
    for i, c in counts.items():
        dv = {t: (1+math.log10(tf))*idf[t] for t, tf in c.items()}
        dot = sum(dv.get(t, 0)*v for t, v in qv.items())
        if dot:
            score = dot/math.sqrt(sum(v*v for v in dv.values())*sum(v*v for v in qv.values()))
            expected.append((i, score))
    expected.sort(key=lambda x: (-x[1], x[0]))
    actual = index.rank("red shoes")
    assert [i for i, _ in actual] == [i for i, _ in expected]
    assert [s for _, s in actual] == pytest.approx([s for _, s in expected])
    assert index.rank("unknown") == []
    assert index.rank("red", allowed={3})[0][0] == 3
    index.close()


def test_stemming_and_normalization():
    analyzer = Analyzer("spanish")
    assert analyzer.tokens("CAMISETAS y camisetas") == analyzer.tokens("camiseta camiseta")
    assert analyzer.tokens("café") == analyzer.tokens("cafe")


@pytest.mark.parametrize("metric", ["COSINE", "L2"])
def test_ivf_full_probes_equals_exact_and_numpy(tmp_path, metric):
    rng = np.random.default_rng(55)
    vectors = rng.normal(size=(230, 32)).astype(np.float32)
    vectors[0] = 0
    ids = [pack_rid(RID(i+1, 0)) for i in range(len(vectors))]
    index = IVFIndex.build(tmp_path / metric, ids, vectors, clusters=9, metric=metric)
    index.close()
    counter = DiskCounter()
    index = IVFIndex(tmp_path / metric, counter)
    q = rng.normal(size=32).astype(np.float32)
    expected = sorted(zip(ids, [distance(v, q, metric) for v in vectors]), key=lambda x: (x[1], x[0]))[:10]
    exact = index.search(q, exact=True)
    assert [i for i, _ in exact] == [i for i, _ in expected]
    assert index.search(q, probes=9) == exact
    counter.reset()
    subset = index.search(q, probes=1)
    few_reads = counter.disk_reads
    counter.reset()
    index.search(q, probes=9)
    assert few_reads < counter.disk_reads
    allowed = set(ids[10:30])
    assert all(i in allowed for i, _ in index.search(q, probes=9, allowed=allowed))
    assert len(index.search(q, radius=0, exact=True)) == 0
    with pytest.raises(ValueError):
        index.search([1, 2])
    with pytest.raises(ValueError):
        index.search([float("nan")]*32)
    index.close()
