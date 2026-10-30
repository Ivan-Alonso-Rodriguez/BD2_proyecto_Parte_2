"""Bootstrap de un paso: python setup.py --full. No es un paquete setuptools."""
import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full",action="store_true",help="Descargar dataset, extraer características e importar 10000 productos")
    parser.add_argument("--no-start",action="store_true")
    parser.add_argument("--skip-install",action="store_true")
    parser.add_argument("--port",type=int,default=8000)
    args=parser.parse_args()
    if sys.version_info < (3,10):
        raise SystemExit("Se requiere Python 3.10 o posterior; se recomienda 3.12.")
    os.chdir(ROOT)
    (ROOT/"tmp").mkdir(exist_ok=True)
    os.environ["TEMP"]=os.environ["TMP"]=str(ROOT/"tmp")
    python=ROOT/".venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if not python.is_file():
        venv.create(ROOT/".venv",with_pip=True)
    def run(*arguments):
        subprocess.run([str(python),*arguments],cwd=ROOT,check=True)
    if not args.skip_install:
        run("-m","pip","install","-r","requirements.txt")
    if args.full:
        run("data/fetch_fashion.py")
        run("data/prepare_features.py")
        run("data/build_multimodal.py")
    if not (ROOT/"data/database/multimodal/manifest.json").is_file():
        raise SystemExit("Falta el catálogo. Ejecuta python setup.py --full para descargarlo y construirlo.")
    if not args.no_start:
        run("run.py","--port",str(args.port))


if __name__=="__main__":main()
