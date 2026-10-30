# Atlas · Motor relacional en disco

Entregable 1 de Base de Datos II (CS2042). El repositorio original se completó con páginas binarias, Heap, Sequential, B+ multinivel, Extendible Hashing, SQL, FastAPI y un cliente web. Las tablas y los índices se implementan con `seek`, `read`, `write` y `struct`.

## Ejecutar el proyecto

Con las dependencias instaladas y el entorno virtual activo, inicia el proyecto desde la raíz:

```powershell
python run.py
```

Para preparar el entorno por primera vez:

Requiere Python 3.10 o posterior; el entorno verificado usa Python 3.12.14. `requirements-lock.txt` registra las versiones exactas de esa validación. Ejecuta los comandos desde la raíz del repositorio. No se necesita Node para usar el sistema.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe data/create_demo.py
.venv\Scripts\python.exe run.py
```

Abre **http://127.0.0.1:8000**. El mismo servidor entrega el frontend y la API; no abras `frontend/index.html` directamente. La documentación HTTP está en **http://127.0.0.1:8000/docs**. Detén el servidor con Ctrl+C.

En Linux/macOS usa `.venv/bin/python` en lugar de `.venv\Scripts\python.exe`. Con un entorno activo, todos los ejemplos se reducen a `python ...`.

En esta copia local ya se instaló y verificó `.venv`, y `data/database/` contiene `products` con 500000 filas y `products_demo`. Se puede iniciar directamente con `.venv\Scripts\python.exe run.py`. Para repetir la carga completa, indique una tabla o directorio nuevo, por ejemplo `--data-dir data/otra_carga`. El comando `python run.py --data-dir RUTA --port 8001` permite elegir otro directorio y puerto. Usa un solo proceso escritor: detén el backend antes de importar al mismo directorio.

## Importar un CSV desde el navegador

Pulsa **Importar CSV**, selecciona el archivo y escribe el nombre de la nueva tabla. El **límite de filas es opcional**: vacío importa todas; con un número importa como máximo esa cantidad, aunque el archivo tenga menos. Puedes elegir Heap o Sequential y detectar el separador o indicar coma, punto y coma o tabulación.

El CSV debe tener encabezados y codificación UTF-8 (con o sin BOM); el límite de subida es 256 MB. Los nombres se normalizan a identificadores SQL (por ejemplo, `Nombre del artículo` pasa a `nombre_del_articulo`). Se rechazan encabezados vacíos o que generen nombres repetidos. Las columnas aparecen en el explorador al completar la importación.

El motor determina `INT`, `FLOAT` y `CHAR(n)` leyendo todas las filas seleccionadas. Los códigos con ceros iniciales, valores vacíos y columnas con mezcla de números y texto se conservan como texto. Las longitudes CHAR se calculan en bytes UTF-8. Se agrega `_row_id INT PRIMARY KEY` con valores consecutivos desde 1, conservando las columnas originales; así también se pueden importar CSV sin una clave única. El registro completo debe caber en una página del motor.

La carga lee el archivo por bloques y realiza dos pasadas sin guardar todas las filas en RAM. Primero valida e infiere el esquema y después escribe mediante `TableStorage` y los archivos del motor. La nueva tabla se publica en el catálogo al finalizar. Los errores controlados descartan la carga temporal y una tabla existente se conserva. No hay recuperación transaccional ante caída del proceso durante la publicación de archivos.

Al terminar se muestra el número de filas importadas y queda preparado `SELECT * FROM nombre_tabla;` en el editor. El I/O reportado cuenta las páginas binarias creadas y escritas por el motor, excluyendo la subida y la lectura del CSV; el tiempo incluye la inferencia y la carga en el servidor. El importador de productos por consola sigue disponible con su esquema específico.

## Dataset real: products-500000.csv

Se inspeccionó el archivo proporcionado: **500 000 filas**, 90 764 217 bytes, claves `Index` únicas y ascendentes de 1 a 500 000. `Index` se convierte en `product_id`; `Added Date` en `added_date` y `Internal ID` en `internal_id`. No se presume una fuente externa distinta del archivo recibido.

El importador busca el CSV en `data/raw/`, la raíz del proyecto y la carpeta Descargas del usuario. También admite una ruta explícita:

```powershell
.venv\Scripts\python.exe data/load_products.py --csv "C:\Users\USER\Downloads\products-500000.csv" --limit 500000
```

Cargas parciales independientes, con nombres distintos para no sobrescribir tablas:

```powershell
.venv\Scripts\python.exe data/load_products.py --limit 1000 --table products_1000
.venv\Scripts\python.exe data/load_products.py --limit 10000 --table products_10000
.venv\Scripts\python.exe data/load_products.py --limit 100000 --table products_100000
```

Para Sequential e índices públicos:

```powershell
.venv\Scripts\python.exe data/load_products.py --limit 10000 --table products_seq --organization SEQUENTIAL --indexes BTREE HASH
```

Opciones: `--data-dir`, `--table`, `--organization HEAP|SEQUENTIAL`, `--page-size 1024|2048|4096|8192`, `--indexes BTREE HASH`. Una tabla ya existente produce un error y se conserva. Si una importación falla, sus filas previas permanecen; usa otra tabla o directorio para repetirla.

La carga usa **CSV → RecordSerializer → TableStorage → Heap/Sequential → Page → DiskManager**, manteniendo también los índices. No precalcula un archivo binario externo ni carga el CSV completo en memoria. Cada tabla tiene un Hash privado para validar la PRIMARY KEY; su costo está incluido en las métricas de importación. El informe `TABLA.import.json` queda junto a sus archivos.

Esquema de 394 bytes por registro:

| Campo | Tipo | Campo | Tipo |
|---|---|---|---|
| product_id | INT | name | CHAR(80) |
| description | CHAR(100) | brand | CHAR(50) |
| category | CHAR(40) | price | FLOAT |
| currency | CHAR(3) | stock | INT |
| ean | CHAR(15) | color | CHAR(25) |
| size | CHAR(15) | availability | CHAR(15) |
| added_date | CHAR(15) | internal_id | CHAR(12) |

INT y FLOAT ocupan 8 bytes. CHAR(n) limita **bytes UTF-8**, no caracteres. EAN se conserva como texto, incluyendo ceros iniciales. Los valores demasiado largos se rechazan; no se truncan silenciosamente.

## SQL disponible

Una sentencia por solicitud; identificadores sin comillas e insensibles a mayúsculas, literales de texto con comillas simples. Se exige exactamente una PRIMARY KEY simple.

```sql
CREATE TABLE empleados (
    id INT PRIMARY KEY,
    nombre CHAR(30),
    dept CHAR(20),
    salario FLOAT
) USING HEAP;

INSERT INTO empleados VALUES (101, 'Ada Lovelace', 'Analytics', 5200.0);
SELECT * FROM empleados WHERE id = 101;
CREATE INDEX idx_emp_id ON empleados(id) USING BTREE;
SELECT nombre, salario FROM empleados WHERE id >= 100 AND id <= 500;
CREATE INDEX hash_emp_id ON empleados(id) USING HASH;
DELETE FROM empleados WHERE id = 101;
DELETE FROM empleados WHERE salario < 1000 AND dept = 'Analytics';
DELETE FROM empleados;
DROP TABLE empleados;
```

También se admite `USING SEQUENTIAL`, SELECT sin WHERE, proyección de columnas, operadores `=`, `<`, `>`, `<=`, `>=`, `!=`, `<>` y predicados combinados con AND. Una comilla literal se escribe `'O''Brien'`. No hay JOIN, UPDATE, OR, agregados, NULL ni SQL completo.

`DELETE FROM tabla WHERE ...` elimina todas las filas que cumplen el filtro y actualiza los índices, incluido el de PRIMARY KEY. `DELETE FROM tabla` vacía la tabla y conserva su esquema e índices; la paginación no limita los borrados. `DROP TABLE tabla` elimina del catálogo la tabla y borra sus archivos de datos, overflow e índices (incluidos los directorios Hash). Después se puede crear otra tabla con el mismo nombre. Una tabla inexistente produce un error. Los ejemplos usan la tabla seleccionada en el explorador. «Ejemplos rápidos» prepara consultas, búsquedas por clave y rango, índices, inserciones y borrados con los nombres y tipos de esa tabla. Ajusta los valores de ejemplo antes de ejecutarlos, especialmente la nueva PRIMARY KEY al insertar. Los nombres de índices y de tablas demo evitan colisiones con el catálogo.

El planificador usa índices públicos: igualdad → `IndexScan`; rango con B+ → `IndexRangeScan`; resto → `SeqScan`. Si B+ y Hash aplican a igualdad, prefiere Hash. El índice privado de PRIMARY KEY no se utiliza para seleccionar filas. En Sequential, `SeqScan` puede usar búsqueda binaria y recorrido acotado del archivo ordenado.

## Panel del plan de ejecución

El panel **Plan de ejecución**, debajo de **Resultados**, representa los operadores en orden de ejecución: recorrido completo o acceso a índice, recuperación por RID, filtro, proyección y resultados; para `DELETE`, muestra el borrado y el mantenimiento de índices. En Sequential distingue el recorrido acotado por la PRIMARY KEY del recorrido completo.

- **Ejecutar consulta** muestra el plan real, las filas examinadas, filtradas y devueltas o eliminadas, y las métricas totales de la operación.
- El plan conserva el SQL al que corresponde, la tabla, el índice y el motivo de selección. Se puede plegar el panel. Una consulta fallida retira el plan anterior.

Los tiempos y el I/O son totales por operación; no se atribuyen porcentajes de costo o tiempos a operadores individuales. La elección sigue las reglas del planificador, sin un optimizador basado en estadísticas.

## API y métricas

- `POST /api/query`: `{"sql":"SELECT * FROM products WHERE product_id = 500;", "offset":0, "limit":100}`.
- `POST /api/explain`: `{"sql":"SELECT * FROM products WHERE product_id = 500;"}`. Devuelve el plan sin ejecutar; también admite DELETE.
- `POST /api/tables/import-csv?table_name=mi_tabla&limit=1000&organization=HEAP&delimiter=auto`: cuerpo binario del CSV (`Content-Type: text/csv`). Omitir `limit` importa todas las filas. Devuelve métricas, esquema y correspondencia de encabezados.
- `GET /api/tables`: tablas, columnas, organización, tamaño de página e índices, incluidos los de integridad marcados como internos.
- `POST /api/tables/reorganize`: `{"table_name":"products_seq"}`. Reorganiza principal/overflow y reconstruye todos los índices.
- `GET /api/health`: disponibilidad del backend.

Las respuestas de consultas incluyen `execution_plan`, `rows`, `columns`, `total_rows`, `affected_rows`, `access_path`, `index_name`, `disk_reads`, `disk_writes`, `parse_time_ms` y `exec_time_ms`. La respuesta contiene como máximo 1000 filas. El total se cuenta recorriendo los candidatos; cambiar de página ejecuta de nuevo la consulta.

**Qué se cuenta:** llamadas completadas de lectura/escritura de páginas, incluidas páginas de metadata y asignaciones. El catálogo JSON, aperturas de archivos, `stat`, `rename` y `truncate` no se contabilizan como páginas. No son estimaciones ni mediciones de fallos de caché del SO. Python usa archivos sin buffering, pero el sistema operativo puede mantener caché. No se fuerza `fsync` por escritura.

El contador se reinicia por consulta. Las búsquedas por RID usan un buffer local de hasta 32 páginas de datos, vacío al empezar; las transferencias evitadas no suman lecturas. En benchmarks de igualdad el índice y la recuperación del producto se miden juntos.

## Estructura del código

```text
backend/
├── core/                          Implementación real del gestor
│   ├── storage/                   Almacenamiento físico
│   │   ├── page.py                Cabecera, bitmap, slots y Page Layout
│   │   ├── rid.py                 RID (página, slot)
│   │   ├── disk_counter.py        Lecturas y escrituras realizadas
│   │   ├── disk_manager.py        Offset y seek/read/write de páginas
│   │   └── record_serializer.py   Serialización de tipos mediante struct
│   ├── file_org/                  Organización de archivos
│   │   ├── heap_file.py           Heap y Free-List persistente
│   │   ├── sequential_file.py     Principal ordenado y reorganización
│   │   └── overflow_manager.py    Registros enlazados por RID
│   ├── indexes/                   Índices sobre archivos paginados
│   │   ├── bplus_node.py          Nodos internos/hoja y formato binario
│   │   ├── bplus_tree.py          Descenso, splits y hojas enlazadas
│   │   ├── hash_bucket.py         Bucket y serialización
│   │   ├── hash_directory.py      Directorio paginado
│   │   └── extendible_hash.py     Hashing, doubling y split
│   ├── catalog/                   Esquemas y coordinación tabla/índices
│   │   ├── schema_manager.py      Metadata de tablas e índices
│   │   ├── table_storage.py       Apertura, PRIMARY KEY y mantenimiento
│   │   └── csv_importer.py        Inferencia e importación genérica de CSV
│   └── query_engine/              Parser, Planner y Executor
│       ├── tokenizer.py           Tokens del subconjunto SQL
│       ├── query_models.py        ParsedQuery y predicados
│       ├── parser.py              Gramática y validación sintáctica
│       ├── planner.py             choose_access_path()
│       ├── execution_plan.py      Operadores y descripción del plan
│       └── executor.py            SQL, rutas y métricas
├── api/routes.py                  API REST
├── main.py                        FastAPI y frontend estático
└── tests/                         Pruebas funcionales y de persistencia
frontend/
├── index.html                 Cuatro áreas del cliente
└── src/
    ├── styles.css             Diseño y adaptación de tamaño
    ├── app.js                 Interacción, resultados y métricas
    ├── csv-import.js          Formulario de importación
    ├── execution-plan.js      Visualización del plan
    ├── sql-examples.js        Plantillas basadas en el catálogo
    └── services/api.js        Solicitudes reales a FastAPI
data/
├── products.py                Esquema y lectura streaming del CSV
├── load_products.py           Importador del motor
├── create_demo.py             Datos pequeños de demostración
└── generate_dataset.py        Recorte opcional del CSV original
benchmarks/
├── common.py                  Fixtures físicos y exportación
├── exp1_insercion_masiva.py
├── exp2_busqueda_puntual.py
├── exp3_busqueda_rango.py
├── exp4_sensibilidad_bloque.py
├── run_all.py                 Ejecución secuencial
├── results/                   CSV y evidencia real
└── plots/                     Gráficas de resultados
informe/                       Fuentes LaTeX e informe PDF
tools/                         Inspector, validación y compilación del informe
run.py                         Inicio de todo el sistema
EXPOSICION.md                  Mapa rápido de archivos y funciones
```

El flujo de la aplicación es **Frontend → API REST → `backend/core` → archivos binarios**. `backend/main.py` conecta FastAPI con `QueryExecutor`; el núcleo usa la biblioteca estándar y sus propios módulos, sin depender de FastAPI ni del frontend. El catálogo pertenece al núcleo porque define los esquemas y coordina las escrituras de tablas e índices. `data/` conserva los datasets e importadores y `benchmarks/` ejecuta los experimentos usando este mismo núcleo.

Las cinco carpetas que antes estaban directamente bajo `backend/` se trasladaron a `backend/core/`, incluidos sus auxiliares. Los imports usan `backend.core.storage`, `backend.core.file_org`, `backend.core.indexes`, `backend.core.catalog` y `backend.core.query_engine`; las rutas anteriores ya no existen. El formato de los archivos binarios, los endpoints y `python run.py` se mantienen.

## Pruebas y validaciones

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
```

La última ejecución aprobó **89 pruebas, con 0 fallos**. La suite verifica Page Layout, RID, contador, offset, tipos, Heap/Free-List, Sequential/overflow/reorganización, B+ multinivel y rangos, Hash/doubling, persistencia, SQL, planner, executor y API, incluidos DELETE masivos con mantenimiento de índices y DROP TABLE con recreación, importación genérica de CSV y planes reales o previos sin efectos sobre los datos. Las pruebas usan archivos temporales.

La reorganización a `backend/core/` se verificó con las mismas 41 pruebas antes y después, los cuatro experimentos con 1000 productos y una prueba HTTP/navegador en un proceso nuevo. Esas comprobaciones se guardan en `output/qa/core-refactor/` (excluido de Git); no sustituyen los CSV ni las gráficas históricos. También se compararon la lógica Python y los hashes de los datos/evidencias existentes.

La validación adicional `tools/validate_large_indexes.py` construye B+ y Hash sobre la carga de 500000 filas, los reabre y verifica todas las entradas B+ y 1002 búsquedas por índice.

Para repetir las cuatro importaciones con comparación de cada registro después de reabrir, usa un directorio nuevo:

```powershell
.venv\Scripts\python.exe tools/validate_products.py --data-dir data/validation_nueva
```

`benchmarks/results/import_validation.json` registra las cuatro cargas verificadas (1000, 10000, 100000 y 500000). La carga de 500000 tardó 323.0 s en este equipo; incluye comprobación de PRIMARY KEY. Los tiempos dependen de hardware y caché.

Inspector de archivos reales:

```powershell
.venv\Scripts\python.exe tools/inspect_page.py data/database/products.bin --page 0
.venv\Scripts\python.exe tools/inspect_page.py data/database/products.bin --page 1
```

La página cero muestra metadata; la página uno muestra cabecera, slots y offsets reales. Para otros tamaños usa `--page-size 1024` (o el tamaño del archivo).

## Cuatro benchmarks completos

```powershell
.venv\Scripts\python.exe -m benchmarks.run_all
```

También se ejecutan por separado:

```powershell
.venv\Scripts\python.exe benchmarks/exp1_insercion_masiva.py
.venv\Scripts\python.exe benchmarks/exp2_busqueda_puntual.py
.venv\Scripts\python.exe benchmarks/exp3_busqueda_rango.py
.venv\Scripts\python.exe benchmarks/exp4_sensibilidad_bloque.py
```

Todos aceptan `--csv RUTA`. El experimento 1 usa N = 1000, 10000, 50000, 100000, 250000, 500000. B+ y Hash incluyen un Heap de registros completos más el índice; las otras variantes son tablas sin índice. El CSV ascendente favorece el Sequential y casi no genera overflow; el costo de reorganizar incluye reescribir a fill factor 0.75. Las pruebas con inserciones desordenadas sí fuerzan y verifican overflow.

El experimento 2 usa N=100000 y 1000 consultas con semilla 42, devolviendo media y desviación estándar poblacional. El 3 usa selectividades 0.1%, 1%, 5%, 10% y 25%. Ambos cuentan la recuperación de registros y reutilizan un fixture físico, cuya carga queda fuera de la consulta medida. El 4 reconstruye un B+ con páginas de 1024, 2048, 4096 y 8192; aísla el índice y usa RID como etiquetas de prueba.

Prueba corta opcional:

```powershell
.venv\Scripts\python.exe benchmarks/exp1_insercion_masiva.py --sizes 1000
.venv\Scripts\python.exe benchmarks/exp2_busqueda_puntual.py --n 1000 --queries 20
```

**Estos comandos cortos sobrescriben los CSV/gráficas del mismo experimento.** Para conservar la evidencia completa, cópiala antes o vuelve a ejecutar los tamaños completos. Los fixtures quedan en `benchmarks/work/`, los datos tabulados en `benchmarks/results/` y las gráficas en `benchmarks/plots/`. Datos grandes y fixtures no se versionan; resultados y gráficas sí.



## Límites conocidos

- Un solo proceso escritor. El lock del backend no coordina procesos independientes.
- Sin WAL, transacciones, rollback ni recuperación automática ante interrupción entre varias escrituras. La reorganización completa de tabla e índices no es atómica ante fallos.
- El B+ elimina pares sin merge; el Hash no contrae su directorio ni recupera todas las páginas de colisión retiradas. Reconstruir índices recupera espacio.
- Hash limita la profundidad global a 20 y encadena colisiones/claves repetidas. Las listas largas degradan el rendimiento.
- Sequential se reorganiza explícitamente; el redondeo de slots puede producir una ocupación inferior al 75%, especialmente con páginas pequeñas.
- El catálogo administra metadata en JSON; las tablas, árboles, buckets y directorios siempre usan páginas binarias.
- El informe usa «Equipo del proyecto» porque no se proporcionaron integrantes. La grabación del video de exposición corresponde al equipo; se entrega el guion, no una grabación atribuida a personas.

No se incluyen componentes del Entregable 2.
