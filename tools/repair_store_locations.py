"""Reubica las tiendas sintéticas y reconstruye su R-Tree. Detén antes la API."""
import argparse
import json
import os
from pathlib import Path
import random
import shutil
import struct
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.catalog.schema_manager import SchemaManager
from backend.core.file_org.heap_file import HeapFile
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.record_serializer import RecordSerializer
from backend.core.multimodal.paged import pack_rid
from backend.core.multimodal.rtree import RTree
from data.store_locations import LOCATION_MODEL, LOCATION_SEED, sample_store_location, location_metadata


def repair_locations(directory):
    directory = Path(directory).resolve()
    root = directory / "multimodal"
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("location_generation", {}).get("model") == LOCATION_MODEL:
        return {"records": manifest["n"], "changed": False}
    catalog = SchemaManager(directory)
    table = catalog.get_table(manifest["table"])
    if table.organization != "HEAP" or any(i.column in ("lon", "lat") for i in table.indexes):
        raise ValueError("La reparación requiere Heap y ninguna clave B+/Hash sobre lon o lat")
    serializer = RecordSerializer(table.columns)
    offsets = {name: offset for name, dtype, offset, _ in serializer.fields
               if name in ("lon", "lat") and dtype == "FLOAT"}
    if len(offsets) != 2:
        raise ValueError("Se requieren columnas lon y lat de tipo FLOAT")

    identifier = uuid.uuid4().hex
    backup = directory / ".location-backups" / identifier
    backup.mkdir(parents=True)
    table_path = directory / table.filename
    original_table = backup / table.filename
    original_manifest = backup / "manifest.original.json"
    staged_table = backup / "updated.bin"
    shutil.copy2(table_path, original_table)
    shutil.copy2(manifest_path, original_manifest)
    shutil.copy2(table_path, staged_table)
    geo_path = root / f"geo-inland-{identifier}.idx"
    heap = HeapFile(DiskManager(staged_table, table.page_size), serializer.record_size)
    tree = RTree(geo_path)
    ids, rng = set(), random.Random(LOCATION_SEED)
    try:
        for rid, raw in heap.scan():
            lon, lat = sample_store_location(rng)
            updated = bytearray(raw)
            struct.pack_into("<d", updated, offsets["lon"], lon)
            struct.pack_into("<d", updated, offsets["lat"], lat)
            heap.update(rid, updated)
            tree.insert((lon, lat, lon, lat), rid)
            ids.add(pack_rid(rid))
        if len(ids) != manifest["n"] or tree.count != len(ids):
            raise ValueError("El número de productos no coincide con el manifiesto")
        if {pack_rid(rid) for rid in tree.window((-180, -90, 180, 90))} != ids:
            raise ValueError("El nuevo R-Tree no corresponde a los RID del Heap")
        os.fsync(heap.disk_manager.file.fileno())
        os.fsync(tree.disk.file.fileno())
    finally:
        heap.close()
        tree.close()

    manifest["indexes"]["geo"]["path"] = geo_path.name
    manifest["location_generation"] = location_metadata()
    staged_manifest = backup / "manifest.updated.json"
    staged_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        staged_table.replace(table_path)
        staged_manifest.replace(manifest_path)
    except Exception:
        shutil.copy2(original_table, table_path)
        shutil.copy2(original_manifest, manifest_path)
        raise
    return {"records": len(ids), "changed": True, "backup": str(backup), "geo_index": geo_path.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/database")
    args = parser.parse_args()
    print(json.dumps(repair_locations(args.data_dir), indent=2))


if __name__ == "__main__":
    main()
