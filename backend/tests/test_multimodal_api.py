import io
import json
import math
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.core.query_engine.executor import QueryExecutor
from backend.core.catalog.table_storage import TableStorage
from backend.core.storage.disk_counter import DiskCounter
from backend.core.multimodal.paged import BlobStore, pack_rid
from backend.core.multimodal.rtree import RTree
from backend.core.multimodal.text import InvertedIndex
from backend.core.multimodal.vector import IVFIndex
from backend.core.multimodal.geo import haversine, geographic_mindist, radius_windows
from backend.core.multimodal.sql import MultimodalSQL


@pytest.fixture
def collection(tmp_path):
    engine=QueryExecutor(directory=tmp_path)
    engine.execute("CREATE TABLE productos (id INT PRIMARY KEY, titulo CHAR(180), cuerpo CHAR(512), categoria CHAR(48), precio FLOAT, lon FLOAT, lat FLOAT, imagen INT) USING HEAP;")
    engine.execute("CREATE INDEX precio_btree ON productos(precio) USING BTREE;")
    engine.execute("CREATE INDEX categoria_hash ON productos(categoria) USING HASH;")
    root=tmp_path/"multimodal"
    root.mkdir()
    tree=RTree(root/"geo.idx", max_entries=4)
    blobs=BlobStore(root/"images.blobs")
    photo=io.BytesIO()
    Image.new("RGB",(20,20),"red").save(photo,format="JPEG")
    texts, ids=[],[]
    with TableStorage(engine.schema_manager,engine.schema_manager.get_table("productos"),DiskCounter()) as storage:
        for i in range(40):
            color="red" if i%2 else "blue"
            lon,lat=-77.04+i*.001,-12.10
            rid=storage.insert([i,f"{color} shirt",f"{color} cotton shirt", "Apparel" if i%3 else "Footwear",float(30+i),lon,lat,blobs.append(photo.getvalue())])
            ids.append(pack_rid(rid));texts.append((pack_rid(rid),f"{color} cotton shirt"))
            tree.insert((lon,lat,lon,lat),rid)
    tree.close();blobs.close()
    InvertedIndex.build(root/"text",texts).close()
    rng=np.random.default_rng(42)
    IVFIndex.build(root/"ivf",ids,rng.normal(size=(40,16)),clusters=4).close()
    manifest={"n":40,"table":"productos","dimensions":16,"clusters":4,"indexes":{"geo":{"kind":"RTREE"},"text":{"kind":"INVERTED"},"ivf":{"kind":"IVF"}}}
    (root/"manifest.json").write_text(json.dumps(manifest))
    return tmp_path,engine


def test_hybrid_sql_restart_and_readonly(collection):
    path,_=collection
    engine=QueryExecutor(directory=path)
    result=engine.execute("SELECT id, precio, COSINE_SCORE() AS relevancia FROM productos WHERE cuerpo MATCH 'red AND NOT blue' AND precio < 40 ORDER BY relevancia DESC LIMIT 10;")
    assert {r['id'] for r in result.rows} == {1,3,5,7,9}
    assert result.disk_reads == sum(x['disk_reads'] for x in result.io_breakdown.values())
    assert result.disk_writes == 0
    assert "BTREEFilter(precio)" in result.execution_plan['steps']
    radius=engine.execute("SELECT id, ubicacion FROM productos WHERE ubicacion WITHIN_RADIUS ((-77.04,-12.10),0.25) LIMIT 40;")
    assert {r['id'] for r in radius.rows} == {0,1,2}
    for sql in ("DELETE FROM productos;","DROP TABLE productos;", "INSERT INTO productos VALUES (99, 'x', 'x', 'x', 1, 1, 1, 1);"):
        with pytest.raises(ValueError,match="solo lectura"):
            engine.execute(sql)


def test_vector_sql_pre_filter_and_metric(collection):
    _,engine=collection
    q=json.dumps([.1]*16)
    engine.execute("SET ivf.probes = 4;")
    result=engine.execute(f"SELECT id, precio, embedding <=> '{q}' AS distancia FROM productos WHERE precio < 40 AND cuerpo MATCH 'red' ORDER BY distancia ASC LIMIT 3;")
    assert len(result.rows)==3
    assert all(r['id']%2==1 and r['precio']<40 for r in result.rows)
    assert [r['distancia'] for r in result.rows] == sorted(r['distancia'] for r in result.rows)
    l2=engine.execute(f"SELECT id, embedding <-> '{q}' AS distancia FROM productos ORDER BY distancia ASC LIMIT 5;")
    assert not l2.execution_plan['approximate']
    index=IVFIndex(engine.multimodal.path('ivf'))
    try:
        query=np.asarray([.1]*16,dtype=np.float32)
        expected=sorted(((r[0],float(np.linalg.norm(np.asarray(r[1:],dtype=np.float32)-query))) for r in index.exact.rows()),key=lambda x:(x[1],x[0]))[:5]
        assert [r['distancia'] for r in l2.rows]==pytest.approx([s for _,s in expected])
    finally:index.close()
    with pytest.raises(ValueError):
        engine.execute(f"SELECT id, embedding <=> '{q}' AS distancia FROM productos ORDER BY distancia DESC LIMIT 5;")


def test_create_multimodal_indexes(collection):
    path,engine=collection
    for sql in ("CREATE INDEX geo_new ON productos(ubicacion) USING RTREE;", "CREATE INDEX text_new ON productos(cuerpo) USING INVERTED WITH (scoring='TFIDF_COSINE');", "CREATE INDEX vector_new ON productos(embedding) USING IVF WITH (lists=3,metric='COSINE');"):
        result=engine.execute(sql)
        assert result.disk_writes>0
    reopened=QueryExecutor(directory=path)
    result=reopened.multimodal.search(mode='ivf',reference_id=1,k=3)
    assert len(result.rows)==3
    assert all(row['id']!=1 for row in result.rows)
    assert len(reopened.multimodal.search(text='red',k=10).rows)==10


def test_geographic_knn_with_price_prefilter(collection):
    _,engine=collection
    result=engine.multimodal.search(mode='spatial_knn',radius=(-77.04,-12.10,10),conditions=[('precio','>=',40.)],k=5)
    assert [row['id'] for row in result.rows]==[10,11,12,13,14]
    assert 'RTreeKNN(MINDIST + heap)' in result.execution_plan['steps']


def test_api_filters_validation_and_real_image(collection):
    path,_=collection
    with TestClient(create_app(path)) as client:
        assert client.get('/api/multimodal/status').json()['n']==40
        response=client.post('/api/multimodal/search',json={"mode":"text","text":"red","max_price":40,"category":"Apparel"})
        assert response.status_code==200
        assert all(r['precio']<=40 and r['categoria']=='Apparel' for r in response.json()['rows'])
        assert client.post('/api/multimodal/search',json={"lon":-77}).status_code==400
        assert client.post('/api/multimodal/search',json={"max_price":-5}).status_code==422
        assert client.post('/api/multimodal/search',json={"mode":"ivf","vector":[1,2]}).status_code==400
        assert client.post('/api/multimodal/image-search',content=b'').status_code==400
        image=client.get('/api/multimodal/image/1')
        assert image.status_code==200 and image.content[:2]==b'\xff\xd8'
        assert client.get('/api/multimodal/image/999').status_code==400


def test_map_returns_complete_catalog_and_category_subsets(collection):
    path,_=collection
    with TestClient(create_app(path)) as client:
        preview=client.post('/api/multimodal/search',json={'k':12}).json()
        response=client.post('/api/multimodal/map',json={'k':12})
        assert response.status_code==200
        full=response.json()
        assert len(preview['rows'])==12
        assert len(full['rows'])==full['total_rows']==40
        assert full['execution_plan']['result_scope']=='all_matches'
        assert full['execution_plan']['steps'][-1]=='AllMatches'
        assert full['disk_reads']==sum(x['disk_reads'] for x in full['io_breakdown'].values())
        full_ids={r['id'] for r in full['rows']}
        for category in ('Apparel','Footwear'):
            filtered=client.post('/api/multimodal/map',json={'category':category,'k':12}).json()
            expected={r['id'] for r in full['rows'] if r['categoria']==category}
            assert {r['id'] for r in filtered['rows']}==expected
            assert expected<=full_ids


def test_catalog_pagination_first_middle_last_and_out_of_range(collection):
    path,_=collection
    with TestClient(create_app(path)) as client:
        pages=[client.post('/api/multimodal/search',json={'k':12,'offset':offset}).json()
               for offset in (0,12,24,36,48)]
        assert [len(page['rows']) for page in pages]==[12,12,12,4,0]
        assert all(page['total_rows']==40 and page['limit']==12 for page in pages)
        assert [page['offset'] for page in pages]==[0,12,24,36,48]
        assert [r['id'] for page in pages for r in page['rows']]==list(range(40))
        assert all(page['execution_plan']['result_scope']=='page' for page in pages)
        assert all(page['disk_writes']==0 for page in pages)
        empty=client.post('/api/multimodal/search',json={'category':'absent','k':12}).json()
        assert empty['total_rows']==0 and empty['rows']==[]
        # Cambiar a mapa no debe heredar el desplazamiento de las tarjetas.
        full=client.post('/api/multimodal/map',json={'k':12,'offset':36}).json()
        assert len(full['rows'])==40 and full['offset']==0
        for offset in (-1,1.5,1000001):
            assert client.post('/api/multimodal/search',json={'offset':offset}).status_code==422


@pytest.mark.parametrize('query',[
    {'category':'Apparel','min_price':35,'max_price':65},
    {'text':'red'},
    {'mode':'boolean','text':'red AND NOT blue','category':'Apparel','max_price':65},
    # Todos los términos tienen IDF cero; el booleano aún debe paginar sus coincidencias.
    {'mode':'boolean','text':'cotton AND shirt'},
    {'text':'cotton shirt'},
    {'mode':'spatial','lon':-77.04,'lat':-12.10,'radius':2,'category':'Apparel'},
    {'mode':'spatial_knn','lon':-77.04,'lat':-12.10,'radius':2,'min_price':35},
    {'mode':'exact','reference_id':1,'category':'Apparel'},
    {'mode':'ivf','reference_id':1,'probes':1,'max_price':60},
])
def test_pagination_preserves_filtered_ranking_and_total(collection,query):
    path,_=collection
    with TestClient(create_app(path)) as client:
        full=client.post('/api/multimodal/search',json={**query,'k':100}).json()
        actual=[]
        for offset in range(0,full['total_rows']+5,5):
            response=client.post('/api/multimodal/search',json={**query,'k':5,'offset':offset})
            assert response.status_code==200
            page=response.json()
            assert page['total_rows']==full['total_rows']
            assert page['rows']==full['rows'][offset:offset+5]
            actual.extend(row['id'] for row in page['rows'])
        assert actual==[row['id'] for row in full['rows']]
        assert len(actual)==len(set(actual))


def test_uploaded_image_pagination(collection,monkeypatch):
    path,_=collection
    class Encoder:
        def __init__(self,**kwargs): pass
        def encode(self,images): return np.ones((len(images),16),dtype=np.float32)
    monkeypatch.setattr('backend.core.multimodal.collection.ResNetEncoder',Encoder)
    with TestClient(create_app(path)) as client:
        image=client.get('/api/multimodal/image/1').content
        full=client.post('/api/multimodal/image-search?mode=exact&k=100',content=image).json()
        page=client.post('/api/multimodal/image-search?mode=exact&k=12&offset=12',content=image).json()
        assert page['rows']==full['rows'][12:24]
        assert page['total_rows']==40 and page['offset']==12


def test_bovw_pagination_excludes_reference_and_counts_matches(collection,monkeypatch):
    path,engine=collection
    with TableStorage(engine.schema_manager,engine.schema_manager.get_table('productos'),DiskCounter()) as storage:
        documents=[(pack_rid(rid),{'word-a' if storage.serializer.unpack(raw)['id']%2 else 'word-b':1})
                   for rid,raw in storage.records.scan()]
    InvertedIndex.build(path/'multimodal'/'bovw',documents).close()
    class Codebook:
        def __init__(self,*args): pass
        def encode(self,features): return {'word-a':1}
        def close(self): pass
    monkeypatch.setattr('backend.core.multimodal.collection.VisualWords',Codebook)
    monkeypatch.setattr('backend.core.multimodal.collection.sift',lambda image:np.zeros((1,128)))
    expected=[i for i in range(40) if i%2 and i%3 and i!=1]
    with TestClient(create_app(path)) as client:
        actual=[]
        for offset in (0,5,10,15):
            response=client.post('/api/multimodal/search',json={
                'mode':'bovw','reference_id':1,'category':'Apparel','k':5,'offset':offset})
            assert response.status_code==200
            page=response.json()
            assert page['total_rows']==len(expected)
            assert [row['id'] for row in page['rows']]==expected[offset:offset+5]
            actual.extend(row['id'] for row in page['rows'])
        assert actual==expected


def test_map_preserves_combined_filters_and_all_text_matches(collection):
    path,_=collection
    with TestClient(create_app(path)) as client:
        red=client.post('/api/multimodal/map',json={'text':'red','k':12}).json()
        assert {r['id'] for r in red['rows']}==set(range(1,40,2))
        body={'mode':'boolean','text':'red AND NOT blue','category':'Apparel',
              'min_price':35,'max_price':65,'lon':-77.04,'lat':-12.10,'radius':2,'k':1}
        response=client.post('/api/multimodal/map',json=body)
        assert response.status_code==200
        expected={i for i in range(40) if i%2 and i%3 and 35<=30+i<=65
                  and haversine((-77.04,-12.10),(-77.04+i*.001,-12.10))<=2}
        assert {r['id'] for r in response.json()['rows']}==expected
        assert client.post('/api/multimodal/map',json={'category':'absent'}).json()['rows']==[]
        assert client.post('/api/multimodal/map',json={'lon':-77.04}).status_code==400
        for mode in ('ivf','exact','bovw','spatial_knn'):
            assert client.post('/api/multimodal/map',json={'mode':mode}).status_code==400
        assert client.post('/api/multimodal/search',json={'k':101}).status_code==422


def test_map_is_not_capped_by_normal_search_limit(tmp_path):
    engine=QueryExecutor(directory=tmp_path)
    engine.execute('CREATE TABLE productos (id INT PRIMARY KEY, titulo CHAR(24), categoria CHAR(24), precio FLOAT, lon FLOAT, lat FLOAT) USING HEAP;')
    with TableStorage(engine.schema_manager,engine.schema_manager.get_table('productos'),DiskCounter()) as storage:
        for i in range(1005):
            storage.insert([i,'Producto','Apparel',50.,-77.01,-12.10])
    root=tmp_path/'multimodal'
    root.mkdir()
    (root/'manifest.json').write_text(json.dumps({'table':'productos','n':1005,'indexes':{}}))
    with TestClient(create_app(tmp_path)) as client:
        response=client.post('/api/multimodal/map',json={'k':12})
    assert response.status_code==200
    assert {row['id'] for row in response.json()['rows']}==set(range(1005))


def test_geo_bounds_dateline_poles_and_knn(tmp_path):
    assert len(radius_windows(179.99,0,5))==2
    assert radius_windows(0,89.99,5)[0][0]==-180
    points=[(179.9,0),(-179.9,0),(0,89),(0,-89),(1,1),(20,30)]
    tree=RTree(tmp_path/'geo.idx',max_entries=3)
    from backend.core.storage.rid import RID
    for i,p in enumerate(points):tree.insert(p+p,RID(i+1,0))
    for q in [(180,0),(0,90),(-30,-80)]:
        got=[r.page_id-1 for r,_ in tree.knn(q,3,metric=geographic_mindist)]
        expected=sorted(range(len(points)),key=lambda i:(haversine(q,points[i]),i))[:3]
        assert got==expected
    tree.close()


@pytest.mark.parametrize('sql',[
    "SET ivf.probes = 0;", "SELECT id FROM productos LIMIT -1;",
    "SELECT id FROM productos WHERE cuerpo MATCH 'red'; DROP TABLE productos;",
    "SELECT id FROM productos WHERE ubicacion WITHIN_RADIUS ((1,2),'bad');",
    "SELECT embedding <=> '[true]' AS d FROM productos LIMIT 1;",
])
def test_extended_sql_rejects_invalid_inputs(sql):
    with pytest.raises(ValueError):MultimodalSQL().parse(sql)
