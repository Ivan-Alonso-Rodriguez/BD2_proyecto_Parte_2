"""Único punto de transferencia de páginas entre archivos binarios y memoria."""

import os
from pathlib import Path
from .page import PAGE_SIZE, PageHeader
from .disk_counter import DiskCounter


class DiskManager:
    def __init__(self, filepath, page_size=PAGE_SIZE, counter=None):
        if page_size not in (1024, 2048, 4096, 8192):
            raise ValueError("page_size debe ser 1024, 2048, 4096 u 8192")
        self.filepath = Path(filepath)
        self.kind = ("table" if self.filepath.suffix in (".bin", ".overflow")
                     else "blob" if self.filepath.suffix == ".blobs" else "index")
        self.page_size = page_size
        self.counter = counter if counter is not None else DiskCounter()
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(
            self.filepath, "r+b" if self.filepath.exists() else "w+b", buffering=0
        )
        if os.fstat(self.file.fileno()).st_size % page_size:
            self.close()
            raise ValueError("Archivo truncado o tamaño de página incorrecto")

    # PARTE IMPORTANTE PARA EXPOSICION: OFFSET FISICO Y TRANSFERENCIAS
    def read_page(self, page_id):
        if not 0 <= page_id < self.num_pages():
            raise ValueError(f"Página inexistente: {page_id}")
        offset = page_id * self.page_size
        self.file.seek(offset)
        data = self.file.read(self.page_size)
        if len(data) != self.page_size:
            raise ValueError("Lectura de página incompleta")
        self.counter.register_read(self.kind)
        return data

    def write_page(self, page_id, data):
        if len(data) != self.page_size or not 0 <= page_id < self.num_pages():
            raise ValueError("Escritura de página inválida")
        offset = page_id * self.page_size
        self.file.seek(offset)
        if self.file.write(data) != self.page_size:
            raise OSError("Escritura de página incompleta")
        self.counter.register_write(self.kind)

    def allocate_page(self, data=None):
        page_id = self.num_pages()
        if data is None:
            data = PageHeader(page_id).pack().ljust(self.page_size, b"\0")
        if len(data) != self.page_size:
            raise ValueError("Tamaño de página inválido")
        self.file.seek(page_id * self.page_size)
        if self.file.write(data) != self.page_size:
            raise OSError("Asignación de página incompleta")
        self.counter.register_write(self.kind)
        return page_id

    def num_pages(self):
        return os.fstat(self.file.fileno()).st_size // self.page_size

    def truncate(self):
        self.file.truncate(0)

    def close(self):
        if not self.file.closed:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
