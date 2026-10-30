"""Experimento 6. PostgreSQL se usa solo como baseline aislado, nunca como motor."""
import argparse
import heapq
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.multimodal.text import Analyzer, InvertedIndex
from backend.core.multimodal.paged import FixedArray
from backend.core.storage.disk_counter import DiskCounter
from data.prepare_features import rows
from data.build_multimodal import description
from benchmarks.p2.common import BASE, write_csv, summarize, chart, environment


def full_scan(path, expression_terms, operation, idf, k=10):
    """Escanea texto normalizado materializado y norma; no usa listas de posteo."""
    counter = DiskCounter()
    start = time.perf_counter()
    scan = FixedArray(path, "<Qd1024s", counter)
    query_counts = Counter(expression_terms)
    weights = {t: (1+math.log10(tf))*idf.get(t, 0) for t, tf in query_counts.items()}
    qnorm = math.sqrt(sum(w*w for w in weights.values()))
    found, scores = [], []
    try:
        for doc_id, norm, body in scan.rows():
            counts = Counter(body.rstrip(b"\0").decode().split())
            terms = [t in counts for t in expression_terms]
            if operation == "RANK":
                dot = sum((1+math.log10(counts[t]))*idf[t]*weight for t, weight in weights.items() if counts[t])
                if dot and norm and qnorm:
                    item = (dot/(norm*qnorm), -doc_id)
                    if len(scores) < k:
                        heapq.heappush(scores, item)
                    elif item > scores[0]:
                        heapq.heapreplace(scores, item)
            elif (all(terms) if operation == "AND" else any(terms) if operation == "OR" else terms[0] and not any(terms[1:])):
                found.append(doc_id)
    finally:
        scan.close()
    if operation == "RANK":
        found = [-doc_id for _, doc_id in sorted(scores, reverse=True)]
    return found, (time.perf_counter()-start)*1000, counter.disk_reads


def pg_expression(terms, operation):
    if operation == "AND-NOT":
        return terms[0] + (" & !(" + " | ".join(terms[1:]) + ")" if len(terms) > 1 else "")
    return (" & " if operation == "AND" else " | ").join(terms)


def expression(terms, operation):
    if operation == "AND-NOT":
        return terms[0] + (" AND NOT (" + " OR ".join(terms[1:]) + ")" if len(terms)>1 else "")
    return (" AND " if operation == "AND" else " OR ").join(terms)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="data/fashion/fashion.parquet")
    p.add_argument("--dsn", default="postgresql://atlas_bench:atlas_bench_local@127.0.0.1:55432/atlas_bench")
    p.add_argument("--skip-postgres", action="store_true")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--repeats", type=int, default=3)
    args = p.parse_args()
    output = BASE / ("smoke-results" if args.quick else "results")
    environment(output)
    analyzer = Analyzer()
    docs = [(i+1, description(row)) for i, row in enumerate(rows(args.source, 20000))]
    normalized = {i: " ".join(analyzer.tokens(text)) for i, text in docs}
    conn = None
    if not args.skip_postgres:
        import psycopg
        conn = psycopg.connect(args.dsn, autocommit=True)
        conn.execute("SET enable_seqscan = off")  # Aislar el acceso GIN requerido.
        version = conn.execute("SHOW server_version").fetchone()[0]
        (output/"postgres.json").write_text(json.dumps({"version": version, "page_bytes": 8192,
            "dictionary": "simple sobre los mismos tokens Snowball", "ranker": "ts_rank_cd (no TF-IDF)",
            "buffers": "shared hit/read de EXPLAIN ANALYZE; no equivalen al contador propio de 4 KB"}, indent=2), encoding="utf-8")
    build_rows, raw, plans = [], [], []
    sizes = [1000] if args.quick else [1000, 5000, 10000, 20000]
    pool = [("black", "casual", "men", "shirt", "cotton"), ("blue", "women", "shoe", "sport", "leather"), ("white", "tshirt", "summer", "puma", "red")]
    for n in sizes:
        work = BASE / "work" / f"text-{n}-{time.time_ns()}"
        work.mkdir(parents=True)
        counter, start = DiskCounter(), time.perf_counter()
        index = InvertedIndex.build(work/"index", docs[:n], counter)
        build_ms = (time.perf_counter()-start)*1000
        size = sum((work/"index"/file).stat().st_size for file in ("vocab.dic", "postings.inv"))
        build_rows.append(dict(n=n, method="Inverted", build_ms=build_ms, bytes=size, writes=counter.disk_writes))
        idf = {row[0].rstrip(b"\0").decode(): math.log10(n/row[1]) for row in index.vocab.rows()}
        norms = dict(index.norms.rows())
        scan = FixedArray(work/"fullscan.bin", "<Qd1024s")
        scan.write_all((i, norms[i], normalized[i].encode()) for i, _ in docs[:n])
        scan.close()
        index.close()
        if conn:
            conn.execute("DROP TABLE IF EXISTS atlas_p2_bench_docs")
            conn.execute("CREATE TABLE atlas_p2_bench_docs (id bigint PRIMARY KEY, body text, document tsvector)")
            with conn.cursor().copy("COPY atlas_p2_bench_docs(id,body) FROM STDIN") as copy:
                for i, _ in docs[:n]:
                    copy.write_row((i, normalized[i]))
            start = time.perf_counter()
            conn.execute("UPDATE atlas_p2_bench_docs SET document=to_tsvector('simple',body)")
            conn.execute("CREATE INDEX atlas_p2_gin ON atlas_p2_bench_docs USING gin(document)")
            build_ms = (time.perf_counter()-start)*1000
            conn.execute("ANALYZE atlas_p2_bench_docs")
            size = conn.execute("SELECT pg_relation_size('atlas_p2_gin')").fetchone()[0]
            build_rows.append(dict(n=n, method="PostgreSQL GIN", build_ms=build_ms, bytes=size, writes=""))
        print(f"Exp6 N={n}: construcción medida", flush=True)
        for terms_count in (1, 3, 5):
            for operation in ("AND", "OR", "AND-NOT", "RANK"):
                for repetition in range(args.repeats):
                    terms = [analyzer.tokens(t)[0] for t in pool[repetition%len(pool)][:terms_count]]
                    expected, elapsed, reads = full_scan(work/"fullscan.bin", terms, operation, idf)
                    common = dict(n=n, terms=terms_count, operation=operation, repetition=repetition)
                    raw.append(dict(**common, method="Full scan", ms=elapsed, reads=reads, pg_shared_hit="", pg_shared_read="", returned=len(expected)))
                    counter, start = DiskCounter(), time.perf_counter()
                    index = InvertedIndex(work/"index", counter)
                    try:
                        found = [i for i, _ in index.rank(" ".join(terms), 10)] if operation == "RANK" else index.boolean(expression(terms, operation))
                    finally:
                        index.close()
                    elapsed = (time.perf_counter()-start)*1000
                    # Ranking puede cambiar el orden de empates de coma flotante; comparar scores no es el propósito de este experimento.
                    if operation != "RANK" and set(found) != set(expected):
                        raise AssertionError("Booleano y Full Scan no coinciden")
                    raw.append(dict(**common, method="Inverted", ms=elapsed, reads=counter.disk_reads, pg_shared_hit="", pg_shared_read="", returned=len(found)))
                    if conn:
                        query = pg_expression(terms, operation)
                        statement = "SELECT id FROM atlas_p2_bench_docs WHERE document @@ to_tsquery('simple', %s)"
                        params = [query]
                        if operation == "RANK":
                            statement += " ORDER BY ts_rank_cd(document,to_tsquery('simple',%s)) DESC,id LIMIT 10"
                            params.append(query)
                        # Misma semántica de términos para booleanos; PostgreSQL elige su plan real.
                        start = time.perf_counter()
                        pg_result = conn.execute(statement, params).fetchall()
                        latency = (time.perf_counter()-start)*1000
                        plan = conn.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) "+statement, params).fetchone()[0][0]
                        plans.append({**common, "query": query, "explain": plan})
                        if operation != "RANK" and {r[0] for r in pg_result} != set(expected):
                            raise AssertionError("GIN y Full Scan no coinciden")
                        raw.append(dict(**common, method="PostgreSQL GIN", ms=latency, reads="", pg_shared_hit=plan["Plan"].get("Shared Hit Blocks", 0),
                                        pg_shared_read=plan["Plan"].get("Shared Read Blocks", 0), returned=len(pg_result)))
        write_csv(output/"exp6_build.csv", build_rows)
        write_csv(output/"exp6_raw.csv", raw)
        (output/"exp6_postgres_plans.json").write_text(json.dumps(plans, indent=2), encoding="utf-8")
    if conn:
        conn.close()
    summary = summarize(raw, ["n", "terms", "operation", "method"], ["ms"])
    write_csv(output/"exp6_query.csv", summary)
    chart(build_rows, "n", "build_ms", "method", output/"exp6_build.png", "Documentos N", "Tiempo (ms)", "Construcción del índice invertido", log=True)
    chart(build_rows, "n", "bytes", "method", output/"exp6_size.png", "Documentos N", "Tamaño (bytes)", "Diccionario + posteos frente al índice GIN", log=True)
    selected = [r for r in summary if r["operation"] == "RANK" and r["terms"] == 3]
    chart(selected, "n", "mean_ms", "method", output/"exp6_query.png", "Documentos N", "Latencia media (ms)", "Ranking Top-10 · consulta de 3 términos", log=True)


if __name__ == "__main__":
    main()
