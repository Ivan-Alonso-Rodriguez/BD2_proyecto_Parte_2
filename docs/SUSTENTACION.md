# Guion propuesto de sustentación (7-8 minutos)

Este es un guion para que **cada integrante participe en la grabación real**. Los roles siguientes son una propuesta de presentación, no una atribución histórica de autoría. El repositorio no contiene una grabación que simule la participación del equipo.

| Tiempo | Integrante | Demostración |
|---|---|---|
| 0:00-1:30 | Ivan Alonso Rodriguez Perez | Presentar problema, 10000 productos reales, arquitectura P1→P2; mostrar catálogo y flujo de una búsqueda. |
| 1:30-3:00 | Yacira Nicol Campoverde San Martín | Mapa, radio y k-NN; explicar MBR, mínima ampliación, split y MINDIST. Mostrar el archivo `geo.idx`. |
| 3:00-4:30 | Jorge Armando Martinez Palomino | MATCH booleano, TF-IDF y coseno; mostrar `vocab.dic`, `postings.inv`, normas y plan con B+ de precio. |
| 4:30-6:15 | Leonardo Alberto Montesinos Damian | Subir imagen; comparar SIFT/BoVW, ResNet/IVF y exacto; variar probes; mostrar centroides y listas paginadas. |
| 6:15-7:45 | Los cuatro, intervenciones breves | Cada uno explica un experimento 5-8 y una limitación; cerrar con reproducibilidad, pruebas y conclusiones. |

## Preparación

1. Ejecutar `python setup.py --full` una vez antes de grabar. En las siguientes sesiones: `.venv\Scripts\python.exe run.py`.
2. Abrir `http://127.0.0.1:8000`; tener un terminal en la raíz y el PDF del informe.
3. Usar una foto del dataset y una imagen nueva para evitar una demostración limitada a auto-coincidencias.
4. Explicar que los precios y las coordenadas son sintéticos; las imágenes, categorías y títulos proceden del corpus real.

## Inspección física en vivo

```powershell
python tools/inspect_page.py data/database/productos.bin --page 1
python tools/inspect_multimodal.py data/database/multimodal/geo.idx --page 0
python tools/inspect_multimodal.py data/database/multimodal/geo.idx --page 1
python tools/inspect_multimodal.py data/database/multimodal/text/vocab.dic --page 0
python tools/inspect_multimodal.py data/database/multimodal/text/postings.inv --page 1
python tools/inspect_multimodal.py data/database/multimodal/ivf/lists.ivf --page 0
python tools/inspect_multimodal.py data/database/multimodal/ivf/centroids.dir --page 1
```

Mostrar `byte_offset = page_id × 4096`, número de páginas, magic bytes y contador. En `vocab.dic`, explicar que el offset apunta a la ubicación física de la lista, no a un objeto Python.

## Preguntas que deben poder responder

- ¿Qué se hereda de P1? Heap, RID, DiskManager, B+, Hash y SQL relacional; P2 los integra, no sustituye por una base externa.
- ¿Por qué un R-Tree pierde eficiencia al subir D? Menor fan-out y mayor solapamiento, lo que reduce la poda; separar evidencia observada de afirmaciones universales.
- ¿Por qué no reconstruir el índice invertido por consulta? Perdería persistencia y aumentaría costo proporcional al corpus; solo se leen los términos solicitados.
- ¿Cuál es el denominador de Recall@10? Los 10 vecinos del k-NN exacto sobre el mismo corpus y métrica. Las 100 consultas no están indexadas.
- ¿Por qué BoVW y ResNet difieren? Las palabras visuales describen patrones locales; la red incorpora características aprendidas. La relevancia se mide con `articleType`, no con juicios humanos.
- ¿PostgreSQL es parte del motor? No. Es un contenedor separado para el experimento 6. Sus buffers de 8 KB se reportan aparte.
- ¿Qué falta para producción? Transacciones/WAL, escritores concurrentes, mantenimiento incremental de la colección, seguridad y mejor utilización de páginas IVF.

## Entrega externa

Grabar 5-10 minutos con participación real de todos; añadir la URL del video a la entrega del curso. Verificar que el docente pueda abrir el repositorio y el video. El enlace y permisos del video dependen de la cuenta/plataforma elegida por el equipo.
