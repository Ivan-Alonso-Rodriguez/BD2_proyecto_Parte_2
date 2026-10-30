"""Tablas desde evidencia real y compilación LaTeX del entregable 2."""
import argparse
import csv
import json
import shutil
import statistics
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'benchmarks/p2/results'
REPORT=ROOT/'informe'


def read(name):
    with (RESULTS/(name+'.csv')).open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))


def esc(value):
    value=str(value)
    return ''.join({'_':r'\_', '&':r'\&', '%':r'\%', '#':r'\#', '$':r'\$', '{':r'\{','}':r'\}'}.get(c,c) for c in value)


def num(value,digits=2):return f'{float(value):.{digits}f}'


def table(headers,rows,caption,compact=False):
    style=r'\footnotesize\renewcommand{\arraystretch}{1.0}' if compact else r'\small'
    return '\n'.join([r'\begin{table}[H]\centering'+style,r'\caption{'+caption+'}',
        r'\begin{tabular}{@{}'+'l'+'r'*(len(headers)-1)+r'@{}}\toprule',
        ' & '.join(headers)+r' \\ \midrule', *[' & '.join(map(str,row))+r' \\' for row in rows],r'\bottomrule\end{tabular}\end{table}'])


def figure(names,caption,width=None):
    w=width or ('.48' if len(names)>1 else '.89')
    return '\n'.join([r'\begin{figure}[H]\centering',*[r'\includegraphics[width='+w+r'\textwidth]{../benchmarks/p2/results/'+name+'}' for name in names],r'\caption{'+caption+r'}\end{figure}'])


def generate():
    spatial,dimensions,build,queries,quality,ann=(read(n) for n in ('exp5_spatial','exp5_dimensions','exp6_build','exp6_query','exp7_quality','exp8_ann'))
    raw=read('exp6_raw')
    if {int(r['n']) for r in spatial}!={10000,50000,100000}:raise ValueError('Faltan tamaños completos del experimento espacial')
    if max(int(r['n']) for r in build)<20000:raise ValueError('Falta corpus de 20000 documentos')
    if not any(r['method']=='PostgreSQL GIN' for r in build):raise ValueError('Falta comparación PostgreSQL')
    if any(int(r['queries'])<100 for r in quality+ann):raise ValueError('Se requieren 100 consultas visuales')
    dense=next(r for r in quality if r['method']=='ResNet18+IVF')
    classic=next(r for r in quality if r['method']=='BoVW')
    probes5=next(r for r in ann if int(r['probes'])==5)
    (REPORT/'resumen_generado.tex').write_text(
        'En las 100 consultas visuales separadas, la Precision@10 media fue '+num(dense['mean_precision10'],3)+
        ' con ResNet-18/IVF y '+num(classic['mean_precision10'],3)+' con BoVW. Con cinco probes, IVF alcanzó Recall@10 de '+
        num(float(probes5['mean_recall10'])*100,1)+r'\%, con '+num(probes5['mean_ms'])+' ms y '+num(probes5['mean_reads'])+
        ' lecturas medias por consulta. Estos resultados se derivan de los CSV versionados, no de valores teóricos.\n',encoding='utf-8')
    parts=[r'\clearpage\section{Resultados y análisis}',r'\subsection{Experimento 5: escalabilidad espacial}']
    selected=[r for r in spatial if (r['operation']=='knn' and float(r['parameter'])==20) or (r['operation']=='radius' and float(r['parameter'])==.02)]
    parts.append(table(['N','Consulta','Método','Lecturas','Media ms','Desv. ms'],[[r['n'],'k=20' if r['operation']=='knn' else 'r=0.02',esc(r['method']),num(r['mean_reads']),num(r['mean_ms']),num(r['std_ms'])] for r in selected],'k-NN y radio planar de 0.02 grados; doce centros por tamaño.'))
    parts.append(figure(['exp5_spatial.png'],'Escalabilidad k-NN para k=5,20,50. Eje de I/O logarítmico.'))
    n100=[r for r in selected if int(r['n'])==100000 and r['operation']=='knn']
    tree=next(r for r in n100 if r['method']=='RTree');scan=next(r for r in n100 if r['method']=='Sequential')
    parts.append('Con 100000 puntos y k=20, el R-Tree leyó '+num(tree['mean_reads'])+' bloques en promedio frente a '+num(scan['mean_reads'])+
                 ' del escaneo. La poda evita recorrer la mayoría de las páginas en este conjunto 2D. La comparación k-NN devuelve identificadores: no incluye recuperar filas comerciales del Heap. En radios sí se contabiliza el refinamiento desde el archivo de puntos. Los CSV crudos incluyen los tres radios y todos los k.')
    radius_tree=next(r for r in spatial if int(r['n'])==100000 and r['operation']=='radius' and float(r['parameter'])==.02 and r['method']=='RTree')
    parts.append('En radio r=0.02 y N=100000, el R-Tree con refinamiento lee '+num(radius_tree['mean_reads'])+' bloques, más que el escaneo. Los candidatos espaciales están dispersos en el archivo y provocan relecturas con la caché acotada. Aun así, su latencia es menor al evaluar menos puntos. Un índice selectivo no garantiza por sí solo menor I/O al recuperar datos no agrupados.')
    parts.append(r'\clearpage\subsection{Experimento 5: efecto de la dimensión}')
    rows=[]
    for d in (2,4,8,16,32,64,128):
        a=next(r for r in dimensions if int(r['dimensions'])==d and r['method']=='Sequential')
        b=next(r for r in dimensions if int(r['dimensions'])==d and r['method']=='RTree')
        rows.append([d,num(a['mean_reads']),num(b['mean_reads']),num(a['mean_ms']),num(b['mean_ms'])])
    parts.append(table(['D','Scan I/O','R-Tree I/O','Scan ms','R-Tree ms'],rows,'2000 vectores uniformes por dimensión, doce consultas k=10.'))
    parts.append(figure(['exp5_dimensions.png'],'Costo temporal al aumentar D; escala logarítmica.'))
    crossings=[d for d in (2,4,8,16,32,64,128) if next(float(r['mean_ms']) for r in dimensions if int(r['dimensions'])==d and r['method']=='RTree')>next(float(r['mean_ms']) for r in dimensions if int(r['dimensions'])==d and r['method']=='Sequential')]
    parts.append('El primer D medido donde la media del árbol supera al escaneo es '+str(min(crossings))+'. A dimensiones elevadas, la búsqueda visita una fracción creciente del árbol y disminuye el fan-out. Este cruce depende de la distribución, la implementación y el hardware; no debe generalizarse como una dimensión límite universal.')
    parts.append(r'\clearpage\subsection{Experimento 6: construcción y espacio}')
    parts.append(table(['N','Método','Construcción ms','Índice KiB'],[[r['n'],esc(r['method']),num(r['build_ms']),num(float(r['bytes'])/1024,1)] for r in build],'Construcción y tamaño del diccionario/posteos propios frente al índice GIN.'))
    parts.append(figure(['exp6_build.png','exp6_size.png'],'Crecimiento temporal y espacial. Los archivos de normas se excluyen del tamaño propio solicitado.'))
    parts.append('El índice propio usa registros de diccionario de tamaño fijo y posteos sin compresión; GIN utiliza una representación distinta y comprime identificadores. Los costos de construcción también incluyen trabajo diferente de normalización y de base de datos, por lo que la tabla describe implementaciones completas bajo las condiciones documentadas, no una comparación aislada de un algoritmo idéntico.')
    parts.append(r'\clearpage\subsection{Experimento 6: consultas y transferencias}')
    query_rows,io_rows=[],[]
    for terms in (1,3,5):
        for operation in ('AND','OR','AND-NOT','RANK'):
            selected=[r for r in queries if int(r['n'])==20000 and int(r['terms'])==terms and r['operation']==operation]
            query_rows.append([terms,esc(operation)]+[num(next(r['mean_ms'] for r in selected if r['method']==m)) for m in ('Full scan','Inverted','PostgreSQL GIN')])
            selected=[r for r in raw if int(r['n'])==20000 and int(r['terms'])==terms and r['operation']==operation]
            mean=lambda method,key:statistics.mean(float(r[key]) for r in selected if r['method']==method)
            io_rows.append([terms,esc(operation),num(mean('Full scan','reads'),1),num(mean('Inverted','reads'),1),num(mean('PostgreSQL GIN','pg_shared_hit'),1),num(mean('PostgreSQL GIN','pg_shared_read'),1)])
    parts.append(table(['Términos','Consulta','Full Scan ms','Invertido ms','GIN ms'],query_rows,'Latencias medias sobre 20000 documentos; tres consultas distintas por combinación.',compact=True))
    parts.append(table(['Términos','Consulta','Scan 4K','Inv. 4K','PG hit 8K','PG read 8K'],io_rows,'Transferencias Atlas y buffers PostgreSQL reportados por separado.',compact=True))
    parts.append(r'OR y ranking consultan conjuntos mayores cuando los términos son frecuentes. AND puede reducir resultados por intersección. Los planes PostgreSQL completos permiten distinguir navegación GIN, acceso a Heap y ordenamiento. El ranking ts\_rank\_cd tiene costo y semántica diferentes de TF-IDF/coseno; una menor latencia de Atlas en un caso no demuestra superioridad general frente a PostgreSQL.')
    parts.append(figure(['exp6_query.png'],'Ranking Top-10 de tres términos según tamaño del corpus.',width='.66'))
    parts.append(r'\clearpage\subsection{Experimento 7: BoVW frente a embeddings}')
    parts.append(table(['Método','P@5','P@10','Consulta ms','Extracción ms/img'],[[esc(r['method']),num(r['mean_precision5'],3),num(r['mean_precision10'],3),num(r['mean_ms']),num(r['extraction_ms_per_image'])] for r in quality],'100 imágenes de consulta excluidas del corpus indexado.'))
    parts.append(figure(['exp7_quality.png'],'Relevancia definida por igualdad de articleType.'))
    parts.append('ResNet-18 obtuvo mayor precisión por categoría en este conjunto. BoVW reconoce patrones locales que pueden repetirse entre objetos de categorías distintas, mientras las características profundas incorporan representaciones aprendidas en ImageNet. La extracción densa es más costosa por imagen en la CPU usada. La consulta BoVW incluye cuantización contra el codebook; su carga inicial se reutiliza en este benchmark. Los tiempos de extracción son medias de lotes de preparación, no latencias individuales de una imagen interactiva.')
    parts.append(r'\clearpage\subsection{Experimento 8: recall, latencia e I/O}')
    parts.append(table(['Probes','Recall@10','Media ms','Desv. ms','Lecturas medias'],[[r['probes'],num(float(r['mean_recall10'])*100,1)+r'\%',num(r['mean_ms']),num(r['std_ms']),num(r['mean_reads'])] for r in ann],'Compromiso de IVF contra la búsqueda exacta sobre las mismas 100 consultas.'))
    parts.append(figure(['exp8_recall_latency.png','exp8_reads.png'],'La exploración de más listas aumenta calidad y costo de consulta.'))
    parts.append('Cinco probes ofrecen un punto de operación favorable en estas mediciones: '+num(float(probes5['mean_recall10'])*100,1)+r'\% de recall medio, sin explorar todo el índice. Los cien probes recorren todas las listas y garantizan la equivalencia con el escaneo exacto. Un recall de 100\% observado con menos probes solo aplica a las consultas medidas. La latencia incluye directorio y apertura; el conteo incluye metadata y listas, no recuperación de la ficha comercial.')
    (REPORT/'resultados_generados.tex').write_text('\n\n'.join(parts)+'\n',encoding='utf-8')
    suites=ET.parse(RESULTS/'tests.xml').getroot()
    tests=sum(int(node.attrib.get('tests',0)) for node in suites.findall('testsuite'))
    failures=sum(int(node.attrib.get('failures',0))+int(node.attrib.get('errors',0)) for node in suites.findall('testsuite'))
    env=json.loads((RESULTS/'environment.json').read_text(encoding='utf-8'))
    validation=json.loads((RESULTS/'dataset_validation.json').read_text(encoding='utf-8'))
    text='La última suite registrada ejecutó '+str(tests)+' pruebas, con '+str(failures)+' fallos o errores. Se verificaron '+str(validation['records'])+' registros y '+str(validation['images_verified'])+' imágenes tras reabrir los archivos. El entorno registrado utiliza Python '+esc(env['python'])+' sobre '+esc(env['platform'])+'. Las versiones exactas se guardan en requirements-lock.txt y environment.json.\n'
    (REPORT/'validacion_generada.tex').write_text(text,encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler')
    p.add_argument('--generate-only',action='store_true')
    args=p.parse_args()
    generate()
    if args.generate_only:return
    bundled=ROOT/'.tools/tectonic/tectonic.exe'
    compiler=args.compiler or (str(bundled) if bundled.exists() else shutil.which('tectonic') or shutil.which('pdflatex'))
    if not compiler:raise SystemExit('Instala Tectonic o pdflatex, o usa --compiler RUTA')
    if 'tectonic' in Path(compiler).name.lower():subprocess.run([compiler,'--keep-logs','main.tex'],cwd=REPORT,check=True)
    else:
        for _ in range(2):subprocess.run([compiler,'-interaction=nonstopmode','-halt-on-error','main.tex'],cwd=REPORT,check=True)
    output=ROOT/'output/pdf'
    output.mkdir(parents=True,exist_ok=True)
    shutil.copy2(REPORT/'main.pdf',output/'entregable_2_atlas.pdf')
    print(output/'entregable_2_atlas.pdf')


if __name__=='__main__':main()
