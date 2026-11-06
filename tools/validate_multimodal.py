"""Verifica cobertura, persistencia y correspondencia de RID del catálogo real."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.core.query_engine.executor import QueryExecutor
from backend.core.catalog.table_storage import TableStorage
from backend.core.storage.disk_counter import DiskCounter
from backend.core.multimodal.paged import pack_rid
from backend.core.multimodal.rtree import RTree
from backend.core.multimodal.text import InvertedIndex
from backend.core.multimodal.vector import IVFIndex
from data.store_locations import LOCATION_MODEL, is_store_location


def main():
    engine=QueryExecutor()
    mm=engine.multimodal
    manifest=mm.manifest()
    with TableStorage(engine.schema_manager,engine.schema_manager.get_table('productos'),DiskCounter()) as storage:
        records={pack_rid(rid):storage.serializer.unpack(raw) for rid,raw in storage.records.scan()}
    assert len(records)==manifest['n']>=10000
    tree=RTree(mm.path('geo'))
    assert {pack_rid(rid) for rid in tree.window((-180,-90,180,90))}==set(records)
    tree.close()
    text=InvertedIndex(mm.path('text'))
    assert set(doc_id for doc_id,_ in text.norms.rows())==set(records)
    assert text.n==len(records)
    text.close()
    vector=IVFIndex(mm.path('ivf'))
    assert set(row[0] for row in vector.exact.rows())==set(records)
    q=vector.vector(next(iter(records)))
    exact=vector.search(q,10,exact=True)
    assert vector.search(q,10,probes=vector.centroids.count)==exact
    vector.close()
    images=0
    for row in list(records.values())[::100]:
        assert mm.image(row['id'])[:2]==b'\xff\xd8'
        images+=1
    result={'records':len(records),'all_rids_match_heap_rtree_text_ivf':True,'images_verified':images,'ivf_full_probes_equals_exact':True,
            'dimensions':manifest['dimensions'],'source':manifest['source'],'synthetic_fields':manifest['metadata_synthetic']}
    if manifest.get('location_generation',{}).get('model')==LOCATION_MODEL:
        assert all(is_store_location(row['lon'],row['lat']) for row in records.values())
        result['all_store_locations_inland']=True
    destination=Path('benchmarks/p2/results/dataset_validation.json')
    destination.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
