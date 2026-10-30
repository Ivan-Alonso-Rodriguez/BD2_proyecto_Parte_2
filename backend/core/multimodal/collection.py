"""Planificador híbrido y aplicación de recomendación sobre el motor P1."""
import json
import math
import operator
import re
import time
from pathlib import Path
import numpy as np
from backend.core.catalog.table_storage import TableStorage
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.record_serializer import KeyCodec
from .paged import BlobStore, pack_rid, unpack_rid
from .rtree import RTree
from .text import InvertedIndex
from .vector import IVFIndex, distance
from .features import ResNetEncoder, VisualWords, sift
from .geo import haversine, radius_windows, geographic_mindist
from .sql import MultimodalSQL

OPS = {"=": operator.eq, "<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt, "!=": operator.ne, "<>": operator.ne}


class MultimodalCollection:
    def __init__(self, engine):
        self.engine = engine
        self.root = engine.schema_manager.directory / "multimodal"
        self.manifest_path = self.root / "manifest.json"
        self.probes, self.encoder = 5, None

    @property
    def ready(self):
        return self.manifest_path.is_file()

    def manifest(self):
        if not self.ready:
            raise ValueError("Falta preparar el dataset. Ejecuta python setup.py --full")
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def path(self, role, manifest=None):
        manifest = manifest or self.manifest()
        return self.root / manifest["indexes"][role].get("path", "geo.idx" if role == "geo" else role)

    def _result(self, rows, counter, start, steps, candidates=0, approximate=False, **extra):
        from backend.core.query_engine.executor import QueryResult
        result = QueryResult(rows=rows, columns=list(rows[0]) if rows else [], total_rows=len(rows),
                             disk_reads=counter.disk_reads, disk_writes=counter.disk_writes,
                             exec_time_ms=(time.perf_counter()-start)*1000, access_path=" → ".join(steps),
                             message=f"{len(rows)} resultados", io_breakdown=counter.breakdown())
        result.execution_plan = {"strategy": "Pre-filtering + refine" if any("Filter" in s for s in steps) else "Index retrieval",
                                 "steps": steps, "candidates": candidates, "approximate": approximate,
                                 "probes": extra.get("probes", self.probes), "io_breakdown": counter.breakdown(),
                                 "note": "Transferencias de páginas de 4096 bytes; caché del SO no controlada."}
        return result

    def search(self, mode="text", text="", k=20, conditions=None, radius=None, vector=None,
               reference_id=None, probes=None, image=None, metric=None, order=None):
        info = self.manifest()
        if mode not in ("text", "boolean", "ivf", "exact", "bovw", "spatial", "spatial_knn", "browse") or not 1 <= k <= 1000:
            raise ValueError("Modo o cantidad de resultados inválidos")
        probes = self.probes if probes is None else probes
        if not 1 <= probes <= 10000:
            raise ValueError("probes fuera de rango")
        counter, start, steps = DiskCounter(), time.perf_counter(), []
        table = self.engine.schema_manager.get_table(info["table"])
        conditions = conditions or []
        for column, op, value in conditions:
            if op not in OPS:
                raise ValueError("Operador inválido")
            codec = KeyCodec(table.column(column).dtype)
            codec.pack(value)
        allowed, scored, candidate_count, extraction_ms = None, None, 0, 0.
        with TableStorage(self.engine.schema_manager, table, counter) as storage:
            # Predicados relacionales: intersectar candidatos de B+ y Hash antes del ranking.
            for column, op, value in conditions:
                definition = next((i for i in table.indexes if i.column == column and (i.kind == "BTREE" or op == "=")), None)
                candidates = None
                if definition:
                    index = storage.indexes[definition.name]
                    if op == "=":
                        candidates = index.search(value)
                    elif op in ("<", "<=", ">", ">=") and definition.kind == "BTREE":
                        candidates = index.range_search(value if op in (">", ">=") else None, value if op in ("<", "<=") else None)
                    if candidates is not None:
                        selected = {pack_rid(rid) for rid in candidates}
                        allowed = selected if allowed is None else allowed & selected
                        steps.append(f"{definition.kind}Filter({column})")
            if conditions:
                stream = storage.records.scan() if allowed is None else storage.fetch_rids(unpack_rid(i) for i in sorted(allowed))
                selected = set()
                for rid, raw in stream:
                    row = storage.serializer.unpack(raw)
                    if all(OPS[op](row[column], value) for column, op, value in conditions):
                        selected.add(pack_rid(rid))
                allowed = selected
                steps.append("RelationalRefine")
            if radius:
                lon, lat, r = radius
                tree = RTree(self.path("geo", info), counter)
                try:
                    candidate_rids = set()
                    for window in radius_windows(lon, lat, r):
                        candidate_rids.update(tree.window(window))
                    selected = set()
                    for rid, raw in storage.fetch_rids(sorted(candidate_rids)):
                        row = storage.serializer.unpack(raw)
                        if haversine((lon, lat), (row["lon"], row["lat"])) <= r+1e-9:
                            selected.add(pack_rid(rid))
                    allowed = selected if allowed is None else allowed & selected
                    steps.extend(["RTreeWindowFilter", "HaversineRefine"])
                finally:
                    tree.close()
            ref_rid = None
            if reference_id is not None:
                pk = next(i for i in table.indexes if i.internal)
                matches = storage.indexes[pk.name].search(reference_id)
                if not matches:
                    raise ValueError("Producto de referencia inexistente")
                ref_rid = pack_rid(matches[0])
            if text.strip() and mode in ("ivf", "exact", "bovw"):
                lexical = InvertedIndex(self.path("text", info), counter)
                try:
                    if re.search(r"\b(?:AND|OR|NOT)\b", text):
                        selected = set(lexical.boolean(text))
                    else:
                        selected = {doc for term in lexical.analyzer.tokens(text) for doc, _ in lexical.term(term)}
                    allowed = selected if allowed is None else allowed & selected
                    steps.append("InvertedTextFilter")
                finally:
                    lexical.close()
            if mode in ("ivf", "exact"):
                index = IVFIndex(self.path("ivf", info), counter)
                try:
                    if image is not None:
                        extract_start = time.perf_counter()
                        if self.encoder is None:
                            self.encoder = ResNetEncoder(cache=Path(__file__).resolve().parents[3] / ".cache/torch")
                        vector = self.encoder.encode([image])[0]
                        extraction_ms = (time.perf_counter()-extract_start)*1000
                    elif ref_rid is not None:
                        vector = index.vector(ref_rid)
                    if vector is None:
                        raise ValueError("Selecciona una imagen, un producto o un vector de consulta")
                    if metric is not None and metric != index.metric:
                        # Los vectores ResNet del corpus están normalizados. L2 exacta
                        # usa esos mismos vectores, sin interpretar una métrica distinta como IVF coseno.
                        if metric != "L2":
                            raise ValueError("Métrica incompatible")
                        q = np.asarray(vector, dtype=np.float32)
                        if q.shape != (index.d,) or not np.isfinite(q).all():
                            raise ValueError(f"Se requiere un vector finito de {index.d} dimensiones")
                        import heapq
                        scored = heapq.nsmallest(k, ((r[0], distance(np.asarray(r[1:], dtype=np.float32), q, "L2")) for r in index.exact.rows() if (allowed is None or r[0] in allowed) and r[0] != ref_rid), key=lambda x: (x[1], x[0]))
                        candidate_count = index.n
                        steps.append("ExactL2Scan")
                        mode = "exact"
                    else:
                        scored = index.search(vector, k, probes, allowed, mode == "exact", exclude=ref_rid)
                        candidate_count = index.last_candidates
                        steps.append("ExactVectorScan" if mode == "exact" else f"IVF(probes={min(probes, index.centroids.count)})")
                finally:
                    index.close()
            elif mode == "bovw":
                if image is None and ref_rid is not None:
                    raw = storage.records.get(unpack_rid(ref_rid))
                    page = storage.serializer.unpack(raw)["imagen"]
                    blobs = BlobStore(self.root / "images.blobs", counter)
                    try:
                        image = blobs.get(page)
                    finally:
                        blobs.close()
                if image is None:
                    raise ValueError("BoVW requiere una imagen o producto de referencia")
                extract_start = time.perf_counter()
                codebook = VisualWords(self.root / "codebook.idx", counter)
                try:
                    words = codebook.encode(sift(image))
                finally:
                    codebook.close()
                extraction_ms = (time.perf_counter()-extract_start)*1000
                index = InvertedIndex(self.root / "bovw", counter)
                try:
                    scored = index.rank(words, k+1, allowed)
                    candidate_count = index.last_candidates
                    scored = [(i, s) for i, s in scored if i != ref_rid][:k]
                finally:
                    index.close()
                steps.extend(["SIFT + Codebook", "BoVW TFIDF Cosine"])
            elif mode in ("text", "boolean") and text.strip():
                index = InvertedIndex(self.path("text", info), counter)
                try:
                    is_boolean = mode == "boolean" or bool(re.search(r"\b(?:AND|OR|NOT)\b", text))
                    if is_boolean:
                        matches = index.boolean(text)
                        candidate_count = len(matches)
                        eligible = set(matches) if allowed is None else set(matches)&allowed
                        ranked = index.rank(text, k, eligible, boolean=True)
                        # Documentos de norma cero siguen satisfaciendo el booleano.
                        scored = ranked + [(i, 0.) for i in sorted(eligible-set(i for i, _ in ranked))][:max(0, k-len(ranked))]
                    else:
                        scored = index.rank(text, k, allowed)
                        candidate_count = index.last_candidates
                    steps.append("BooleanMerge + TFIDF" if is_boolean else "Inverted TFIDF Cosine")
                finally:
                    index.close()
            elif mode == "spatial_knn":
                if not radius:
                    raise ValueError("k-NN geográfico requiere centro y radio")
                tree = RTree(self.path("geo", info), counter)
                try:
                    scored = [(pack_rid(rid), d) for rid, d in tree.knn(radius[:2], k, metric=geographic_mindist, allowed=allowed)]
                    candidate_count = len(allowed) if allowed is not None else info["n"]
                    steps.append("RTreeKNN(MINDIST + heap)")
                finally:
                    tree.close()
            elif mode == "spatial" and not radius:
                raise ValueError("La búsqueda espacial requiere un centro y radio")
            if scored is None:
                stream = storage.records.scan() if allowed is None else storage.fetch_rids(unpack_rid(i) for i in sorted(allowed))
                collected = [(pack_rid(rid), storage.serializer.unpack(raw)) for rid, raw in stream]
                candidate_count = len(collected)
                if order:
                    column, direction = order
                    table.column(column)
                    collected.sort(key=lambda item: item[1][column], reverse=direction == "DESC")
                scored = [(i, 0.) for i, _ in collected[:k]]
                steps.append("HeapScan" if allowed is None else "RIDFetch")
            rows_by_id = {pack_rid(rid): storage.serializer.unpack(raw) for rid, raw in storage.fetch_rids(unpack_rid(i) for i, _ in scored)}
            result_rows = []
            for doc_id, score in scored:
                row = rows_by_id[doc_id]
                row["imagen_url"] = f"/api/multimodal/image/{row['id']}"
                row["score"] = score
                if radius:
                    row["distancia_km"] = haversine(radius[:2], (row["lon"], row["lat"]))
                result_rows.append(row)
        steps.append("TopK")
        result = self._result(result_rows, counter, start, steps, candidate_count, mode == "ivf" and probes < info["clusters"], probes=probes)
        result.execution_plan["extraction_ms"] = extraction_ms
        return result

    def image(self, product_id):
        info = self.manifest()
        table = self.engine.schema_manager.get_table(info["table"])
        counter = DiskCounter()
        with TableStorage(self.engine.schema_manager, table, counter) as storage:
            pk = next(i for i in table.indexes if i.internal)
            rids = storage.indexes[pk.name].search(product_id)
            if not rids:
                raise ValueError("Imagen no encontrada")
            row = storage.serializer.unpack(storage.records.get(rids[0]))
        blobs = BlobStore(self.root / "images.blobs", counter)
        try:
            return blobs.get(row["imagen"])
        finally:
            blobs.close()

    def execute(self, sql, offset=0, limit=100):
        parsed_at = time.perf_counter()
        query = MultimodalSQL().parse(sql)
        parse_ms = (time.perf_counter()-parsed_at)*1000
        if query["kind"] == "SET":
            self.probes = query["probes"]
            from backend.core.query_engine.executor import QueryResult
            return QueryResult(access_path="SetProbes", message=f"ivf.probes = {self.probes}", parse_time_ms=parse_ms)
        info = self.manifest()
        if query["table"] != info["table"]:
            raise ValueError(f"La colección multimodal registrada es {info['table']}")
        if query["kind"] == "CREATE":
            return self.create_index(query)
        mode = "ivf" if query["vector"] is not None else "text" if query["text"] else "browse"
        expected_order = (query.get("distance_alias"), "ASC") if mode == "ivf" else (query.get("score_alias"), "DESC") if mode == "text" else None
        if query["order"] and expected_order and query["order"] != expected_order:
            raise ValueError("El ranking admite distancia ASC o relevancia DESC según su alias")
        if "score_alias" in query and mode != "text":
            raise ValueError("COSINE_SCORE() requiere MATCH")
        result = self.search(mode=mode, text=query["text"] or "", k=query["limit"], conditions=query["conditions"], radius=query["radius"], vector=query["vector"], metric=query.get("metric"), order=query["order"])
        alias = query.get("distance_alias") or query.get("score_alias")
        available = {c.name for c in self.engine.schema_manager.get_table(info["table"]).columns} | {"ubicacion"}
        if alias:
            available.add(alias)
        if query["projection"] != ["*"] and not set(query["projection"]) <= available:
            raise ValueError("Columna de proyección inexistente")
        for row in result.rows:
            row["ubicacion"] = [row["lon"], row["lat"]]
            if alias:
                row[alias] = row["score"]
        if query["projection"] != ["*"]:
            result.rows = [{c: row[c] for c in query["projection"]} for row in result.rows]
        result.total_rows = len(result.rows)
        result.rows = result.rows[offset:offset+limit]
        result.columns = list(result.rows[0]) if result.rows else query["projection"]
        result.offset, result.limit, result.parse_time_ms = offset, limit, parse_ms
        result.execution_plan["sql"] = sql
        return result

    def create_index(self, query):
        from backend.core.query_engine.executor import QueryResult
        info, counter, start = self.manifest(), DiskCounter(), time.perf_counter()
        role, column = {"RTREE": ("geo", "ubicacion"), "INVERTED": ("text", "cuerpo"), "IVF": ("ivf", "embedding")}[query["index_kind"]]
        if query["column"] != column:
            raise ValueError(f"{query['index_kind']} requiere {column}")
        options = query["options"]
        permitted = {"RTREE": set(), "INVERTED": {"scoring"}, "IVF": {"lists", "metric"}}[query["index_kind"]]
        if set(options)-permitted or options.get("scoring", "TFIDF_COSINE") != "TFIDF_COSINE":
            raise ValueError("Opciones de índice no soportadas")
        self.engine.schema_manager.check_index_name(query["name"])
        if any(i.get("name", role_name) == query["name"] for role_name, i in info["indexes"].items()):
            raise ValueError("Nombre de índice existente")
        destination = self.root / ("custom_"+query["name"]+(".idx" if role == "geo" else ""))
        if destination.exists():
            raise ValueError("Ya existe un archivo con ese nombre de índice")
        table = self.engine.schema_manager.get_table(info["table"])
        if role == "ivf":
            clusters = options.get("lists", math.isqrt(info["n"]))
            metric = options.get("metric", "COSINE")
            if type(clusters) is not int or not 1 <= clusters <= info["n"] or metric not in ("COSINE", "L2"):
                raise ValueError("lists/metric inválidos")
            existing = IVFIndex(self.path("ivf", info), counter)
            try:
                entries = list(existing.exact.rows())
            finally:
                existing.close()
            IVFIndex.build(destination, [r[0] for r in entries], np.asarray([r[1:] for r in entries]), clusters, metric, counter).close()
            info["clusters"] = clusters
        else:
            with TableStorage(self.engine.schema_manager, table, counter) as storage:
                if role == "geo":
                    tree = RTree(destination, counter)
                    try:
                        for rid, raw in storage.records.scan():
                            row = storage.serializer.unpack(raw)
                            tree.insert((row["lon"], row["lat"], row["lon"], row["lat"]), rid)
                    finally:
                        tree.close()
                else:
                    InvertedIndex.build(destination, ((pack_rid(rid), storage.serializer.unpack(raw)["cuerpo"]) for rid, raw in storage.records.scan()), counter).close()
        info["indexes"][role] = {"name": query["name"], "kind": query["index_kind"], "column": column, "path": destination.name}
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.manifest_path)
        return QueryResult(access_path="CreateMultimodalIndex", message=f"Índice {query['name']} construido en páginas de 4 KB", disk_reads=counter.disk_reads, disk_writes=counter.disk_writes, exec_time_ms=(time.perf_counter()-start)*1000, io_breakdown=counter.breakdown())
