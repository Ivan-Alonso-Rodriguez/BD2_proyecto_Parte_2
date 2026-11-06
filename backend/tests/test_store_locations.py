import json
from pathlib import Path
import random

import pytest

from backend.core.catalog.table_storage import TableStorage
from backend.core.multimodal.paged import pack_rid
from backend.core.multimodal.rtree import RTree
from backend.core.query_engine.executor import QueryExecutor
from backend.core.storage.disk_counter import DiskCounter
from data.store_locations import LOCATION_MODEL, LOCATION_SEED, is_store_location, sample_store_location
from tools.repair_store_locations import repair_locations


def test_locations_are_reproducible_and_inside_inland_lima():
    first, second = random.Random(LOCATION_SEED), random.Random(LOCATION_SEED)
    locations = [sample_store_location(first) for _ in range(10000)]
    assert locations == [sample_store_location(second) for _ in range(10000)]
    # Límite exterior conservador, al este de la costa de este sector de Lima.
    assert all(-77.045 < lon < -76.970 and -12.135 < lat < -12.075 for lon, lat in locations)
    assert all(is_store_location(lon, lat) for lon, lat in locations)
    assert not is_store_location(-77.15, -12.16)


@pytest.fixture
def catalog(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    engine.execute("CREATE TABLE productos (id INT PRIMARY KEY, titulo CHAR(48), categoria CHAR(24), precio FLOAT, lon FLOAT, lat FLOAT, imagen INT) USING HEAP;")
    engine.execute("CREATE INDEX precio_btree ON productos(precio) USING BTREE;")
    engine.execute("CREATE INDEX categoria_hash ON productos(categoria) USING HASH;")
    root = tmp_path / "multimodal"
    root.mkdir()
    table = engine.schema_manager.get_table("productos")
    tree = RTree(root / "geo.idx")
    with TableStorage(engine.schema_manager, table, DiskCounter()) as storage:
        for i in range(40):
            lon, lat = -77.15 + i * .00001, -12.16
            rid = storage.insert([i, f"Prenda {i}", "Apparel", 50.5+i, lon, lat, 100+i])
            tree.insert((lon, lat, lon, lat), rid)
    tree.close()
    (root / "manifest.json").write_text(json.dumps({
        "table": "productos", "n": 40, "indexes": {"geo": {"kind": "RTREE"}},
    }), encoding="utf-8")
    return engine, tmp_path


def test_repair_preserves_records_rids_and_relational_indexes(catalog):
    engine, directory = catalog
    table = engine.schema_manager.get_table("productos")
    original_bytes = (directory / table.filename).read_bytes()
    original_geo = (directory / "multimodal/geo.idx").read_bytes()
    with TableStorage(engine.schema_manager, table, DiskCounter()) as storage:
        before = {rid: storage.serializer.unpack(raw) for rid, raw in storage.records.scan()}

    result = repair_locations(directory)

    assert result["changed"] and result["records"] == 40
    assert (Path(result["backup"]) / table.filename).read_bytes() == original_bytes
    assert (directory / "multimodal/geo.idx").read_bytes() == original_geo
    with TableStorage(engine.schema_manager, table, DiskCounter()) as storage:
        after = {rid: storage.serializer.unpack(raw) for rid, raw in storage.records.scan()}
    assert before.keys() == after.keys()
    tree = RTree(engine.multimodal.path("geo"))
    try:
        for rid, row in after.items():
            assert is_store_location(row["lon"], row["lat"])
            assert {k: v for k, v in row.items() if k not in ("lon", "lat")} == {
                k: v for k, v in before[rid].items() if k not in ("lon", "lat")}
            lon, lat = row["lon"], row["lat"]
            assert {pack_rid(r) for r in tree.window((lon-1e-12, lat-1e-12, lon+1e-12, lat+1e-12))} == {pack_rid(rid)}
    finally:
        tree.close()
    assert {r["id"] for r in engine.execute("SELECT id FROM productos WHERE precio >= 55 AND precio <= 60;").rows} == {5, 6, 7, 8, 9}
    assert len(engine.execute("SELECT id FROM productos WHERE categoria = 'Apparel';").rows) == 40
    assert engine.multimodal.manifest()["location_generation"]["model"] == LOCATION_MODEL
    repaired_bytes = (directory / table.filename).read_bytes()
    assert repair_locations(directory)["changed"] is False
    assert (directory / table.filename).read_bytes() == repaired_bytes


def test_publish_failure_restores_original_table_and_manifest(catalog, monkeypatch):
    engine, directory = catalog
    table_path = directory / engine.schema_manager.get_table("productos").filename
    manifest_path = directory / "multimodal/manifest.json"
    original_table, original_manifest = table_path.read_bytes(), manifest_path.read_bytes()
    replace = Path.replace

    def fail_manifest_publish(path, target):
        if Path(target) == manifest_path:
            raise OSError("simulated manifest failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_manifest_publish)
    with pytest.raises(OSError, match="simulated manifest failure"):
        repair_locations(directory)
    assert table_path.read_bytes() == original_table
    assert manifest_path.read_bytes() == original_manifest
