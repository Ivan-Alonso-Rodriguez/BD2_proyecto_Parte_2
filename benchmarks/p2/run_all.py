"""Ejecuta P2; usa --quick para pruebas pequeñas sin sobrescribir evidencia completa."""
import argparse
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--skip-postgres',action='store_true')
    args=parser.parse_args()
    for module in ('spatial','textual','visual'):
        flags=['--quick'] if args.quick else []
        if module=='textual' and args.skip_postgres:flags.append('--skip-postgres')
        subprocess.run([sys.executable,'-m',f'benchmarks.p2.{module}',*flags],check=True)


if __name__=='__main__':main()
