"""Inicio único: API + frontend en http://127.0.0.1:8000."""

import argparse
import os
from pathlib import Path
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data-dir", default="data/database")
    args = parser.parse_args()
    os.environ["BD2_DATA_DIR"] = args.data_dir
    env_file = Path(__file__).resolve().parent / ".env"
    uvicorn.run("backend.main:app", host=args.host, port=args.port, workers=1,
                env_file=str(env_file) if env_file.is_file() else None)


if __name__ == "__main__":
    main()
