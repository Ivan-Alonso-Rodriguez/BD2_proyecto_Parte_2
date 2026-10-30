# Trazabilidad del entregable 2

| Requisito | Implementación | Evidencia |
|---|---|---|
| Páginas 4 KB, RID y contador | `backend/core/storage`, `multimodal/paged.py` | Tests P1/P2, inspector físico |
| R-Tree persistente, inserción, splits | `multimodal/rtree.py` | Tests recursivos en D=2,4,16,128; experimento 5 |
| Ventana/radio/k-NN con MINDIST | `rtree.py`, `geo.py`, `collection.py` | Oráculos por fuerza bruta, casos antimeridiano/polos |
| Mapa interactivo | `frontend/src/studio.js`, Leaflet local | QA del navegador, captura `docs/images/map.png` |
| Texto normalizado, stoplists, stemming | `multimodal/text.py`, `stopwords/` | Tests de español, corpus de moda inglés |
| vocab.dic + postings.inv en disco | `InvertedIndex`, `FixedArray` | Reapertura y consulta sin reconstrucción |
| AND/OR/AND-NOT lineal, coseno TF-IDF | `merge`, `boolean`, `rank` | Oráculos de conjuntos y fórmula independiente |
| SIFT + K-Means + BoVW | `features.py`, `vector.kmeans` | 100 imágenes de consulta separadas, experimento 7 |
| Embeddings profundos reales | ResNet-18 ImageNet 512D | `features.json`, SHA de dataset, extracción real |
| k-NN/rango exacto L2/coseno | `vector.py` | IVF con todos los probes coincide con exacto |
| IVF persistente | `centroids.dir`, `lists.ivf`, `vectors.vec` | Experimento 8 con probes 1,2,5,10,20,50,100 |
| SQL extendido y CREATE INDEX | `multimodal/sql.py`, `collection.py` | Tests SQL/API, consola funcional |
| Planificación híbrida e I/O separado | B+/Hash → R-Tree/texto → IVF → refine | Tests de precio + texto + vector; métricas suman total |
| Recomendador ≥10000 productos | `data/fetch_fashion.py`, `prepare_features.py`, `build_multimodal.py` | `dataset_validation.json` |
| Experimentos 5-8, tablas y gráficos | `benchmarks/p2` | CSV crudos, resúmenes, PNG y planes PostgreSQL |
| Backend, frontend, data, benchmarks | Carpetas del repositorio | Inicio con `python setup.py --full` |
| Informe PDF compilado de LaTeX | `informe/main.tex`, `tools/build_p2_report.py` | `informe/main.pdf` |
| Video 5-10 min, todo el equipo | `docs/SUSTENTACION.md` | Guion listo; grabación y enlace a cargo del equipo |

El benchmark espacial de radio usa coordenadas en grados y radios 0.005/0.02/0.05 grados para comparar estructuras bajo la misma métrica planar. La aplicación calcula el radio geográfico en kilómetros mediante Haversine. El experimento de dimensión usa 2000 vectores uniformes por D; la escalabilidad 2D sí llega a 100000 puntos.
