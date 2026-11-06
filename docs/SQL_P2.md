# SQL multimodal

La API común es `POST /api/query`, cuerpo `{"sql":"...", "offset":0, "limit":100}`. Una sentencia por solicitud; comillas simples para texto. La colección se llama `productos`.

```sql
SELECT id, titulo, COSINE_SCORE() AS relevancia
FROM productos
WHERE cuerpo MATCH 'blue shirt'
ORDER BY relevancia DESC LIMIT 10;

SELECT id, titulo, precio, COSINE_SCORE() AS relevancia
FROM productos
WHERE cuerpo MATCH '(black OR blue) AND shoes AND NOT women'
AND precio <= 250 AND categoria = 'Footwear'
ORDER BY relevancia DESC LIMIT 10;

SELECT id, titulo, ubicacion FROM productos
WHERE ubicacion WITHIN_RADIUS ((-77.04, -12.10), 2.5)
LIMIT 20;

SET ivf.probes = 10;

CREATE INDEX geo_v2 ON productos(ubicacion) USING RTREE;
CREATE INDEX texto_v2 ON productos(cuerpo)
USING INVERTED WITH (scoring = 'TFIDF_COSINE');
CREATE INDEX visual_v2 ON productos(embedding)
USING IVF WITH (lists = 100, metric = 'COSINE');
```

La sintaxis vectorial es `SELECT id, embedding <=> '[vector completo]' AS distancia FROM productos WHERE precio <= 250 ORDER BY distancia ASC LIMIT 5;`. El literal JSON debe contener exactamente **512 números finitos** en el catálogo real. No se aceptan puntos suspensivos. `<=>` usa coseno; `<->` calcula L2 exacta contra los vectores persistidos. Los embeddings del catálogo están normalizados; para L2 se conserva el vector de consulta tal como se proporciona. Para obtener recomendaciones sin pegar 512 valores, usa la interfaz o `reference_id` en la API.

`ubicacion` es una columna virtual `[lon,lat]`; `embedding` referencia el archivo vectorial. El resto son columnas reales del Heap. Ranking textual admite `ORDER BY alias DESC`; vectorial, `ORDER BY alias ASC`. El ranking completo toma `LIMIT` antes de aplicar la paginación HTTP. `SET` es configuración del único proceso servidor, compartida entre clientes; la API de búsqueda acepta `probes` por solicitud.

API de aplicación:

```json
{
  "mode": "ivf",
  "reference_id": 15970,
  "category": "Apparel",
  "max_price": 250,
  "lon": -77.04,
  "lat": -12.10,
  "radius": 5,
  "probes": 5,
  "k": 12,
  "offset": 0
}
```

Enviar a `POST /api/multimodal/search`. Modos: `text`, `boolean`, `ivf`, `exact`, `bovw`, `spatial`, `spatial_knn`, `browse`. Un filtro espacial exige lon/lat/radius juntos. `spatial_knn` ordena los más cercanos dentro del radio y demás filtros.

`k` es el tamaño de página (1–100; por defecto 20) y `offset` el número de coincidencias a saltar (0–1000000; por defecto 0). Para páginas de 12, enviar `offset=0`, `12`, `24`, etc. La respuesta incluye `rows`, `total_rows` (total que cumple la búsqueda), `offset`, `limit` y `execution_plan.result_scope="page"`. Un desplazamiento posterior al último resultado devuelve filas vacías conservando el total. Se pagina después del filtrado y ranking, con desempate estable por RID. IVF cuenta solo las coincidencias de las listas exploradas; subir `probes` puede cambiar ese total. La consola SQL conserva su semántica de `LIMIT`.

`POST /api/multimodal/map` acepta los mismos filtros en catálogo, texto y radio, e ignora `offset` para devolver todas las coincidencias (`result_scope="all_matches"`). No admite modos visuales ni `spatial_knn`.

Para una foto propia: `POST /api/multimodal/image-search?mode=ivf&k=12&offset=0&probes=5`, cuerpo binario JPEG/PNG/WebP; máximo 10 MB y 25 megapíxeles. Acepta el mismo desplazamiento para paginar. Cambiar `mode=bovw` o `mode=exact` compara las representaciones.

No se soportan JOIN, agregaciones, UPDATE ni SQL completo. El índice invertido implementa AND, OR, AND NOT, AND-NOT, NOT y paréntesis; precedencia NOT > AND > OR. La frase sin operadores en MATCH solicita ranking de términos. Los documentos sin peso TF-IDF positivo pueden aparecer con score 0 en consultas booleanas para no perder coincidencias válidas.
