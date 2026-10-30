"""Primitivas binarias paginadas. Ninguna consulta carga un archivo completo."""
import struct
from collections import OrderedDict
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.rid import RID

PAGE_SIZE = 4096
ARRAY_HEADER = struct.Struct("<8sIIQ")
BLOB_HEADER = struct.Struct("<4sIIi")


def pack_rid(rid):
    if rid[0] < 0 or not 0 <= rid[1] < 2**32:
        raise ValueError("Los índices multimodales requieren RID de Heap")
    return (rid[0] << 32) | rid[1]


def unpack_rid(value):
    return RID(value >> 32, value & 0xFFFFFFFF)


class PageCache:
    """LRU acotada, creada de nuevo para cada consulta; misses llegan a DiskManager."""
    def __init__(self, disk, capacity=32):
        self.disk, self.capacity, self.pages = disk, capacity, OrderedDict()

    def read(self, page):
        if page not in self.pages:
            self.pages[page] = self.disk.read_page(page)
            if len(self.pages) > self.capacity:
                self.pages.popitem(last=False)
        self.pages.move_to_end(page)
        return self.pages[page]


class FixedArray:
    """Registros de struct de ancho fijo; no cruzan límites de página."""
    def __init__(self, path, fmt, counter=None):
        self.codec = struct.Struct(fmt)
        self.disk = DiskManager(path, counter=counter)
        self.capacity = PAGE_SIZE // self.codec.size
        if not self.capacity:
            self.disk.close()
            raise ValueError("El registro excede 4 KB")
        self.count = 0
        if self.disk.num_pages():
            magic, size, page_size, self.count = ARRAY_HEADER.unpack_from(self.disk.read_page(0))
            if (magic, size, page_size) != (b"ATARRAY2", self.codec.size, PAGE_SIZE):
                self.close()
                raise ValueError("Arreglo incompatible")
        else:
            self.disk.allocate_page(self._header())
        self.cache = PageCache(self.disk)

    def _header(self):
        return ARRAY_HEADER.pack(b"ATARRAY2", self.codec.size, PAGE_SIZE, self.count).ljust(PAGE_SIZE, b"\0")

    def write_all(self, rows):
        if self.count or self.disk.num_pages() != 1:
            raise ValueError("El arreglo ya contiene datos")
        page, used = bytearray(PAGE_SIZE), 0
        for row in rows:
            self.codec.pack_into(page, used * self.codec.size, *row)
            self.count += 1
            used += 1
            if used == self.capacity:
                self.disk.allocate_page(bytes(page))
                page, used = bytearray(PAGE_SIZE), 0
        if used:
            self.disk.allocate_page(bytes(page))
        self.disk.write_page(0, self._header())

    def get(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        page, slot = divmod(index, self.capacity)
        return self.codec.unpack_from(self.cache.read(page + 1), slot * self.codec.size)

    def rows(self):
        for page_id in range(1, self.disk.num_pages()):
            page = self.disk.read_page(page_id)
            count = min(self.capacity, self.count - (page_id - 1) * self.capacity)
            for slot in range(count):
                yield self.codec.unpack_from(page, slot * self.codec.size)

    def find(self, key):
        low, high = 0, self.count
        while low < high:
            mid = (low + high) // 2
            row = self.get(mid)
            if row[0] < key:
                low = mid + 1
            else:
                high = mid
        if low < self.count:
            row = self.get(low)
            if row[0] == key:
                return row
        return None

    def close(self):
        self.disk.close()


class BlobStore:
    """JPEG originales en cadenas de páginas, referenciados desde el Heap."""
    def __init__(self, path, counter=None):
        self.disk = DiskManager(path, counter=counter)
        if not self.disk.num_pages():
            self.disk.allocate_page(b"ATBLOB2".ljust(PAGE_SIZE, b"\0"))
        elif not self.disk.read_page(0).startswith(b"ATBLOB2"):
            self.close()
            raise ValueError("Archivo de blobs incompatible")

    def append(self, data):
        if not data:
            raise ValueError("Blob vacío")
        capacity = PAGE_SIZE - BLOB_HEADER.size
        first = self.disk.num_pages()
        for offset in range(0, len(data), capacity):
            chunk = data[offset:offset + capacity]
            page = self.disk.num_pages()
            nxt = page + 1 if offset + capacity < len(data) else -1
            raw = BLOB_HEADER.pack(b"BLB2", page, len(chunk), nxt) + chunk
            self.disk.allocate_page(raw.ljust(PAGE_SIZE, b"\0"))
        return first

    def get(self, page):
        chunks, seen = [], set()
        while page != -1:
            if page in seen or len(seen) > 4096:
                raise ValueError("Cadena de blob corrupta")
            seen.add(page)
            raw = self.disk.read_page(page)
            magic, actual, length, nxt = BLOB_HEADER.unpack_from(raw)
            if magic != b"BLB2" or actual != page or length > PAGE_SIZE - BLOB_HEADER.size:
                raise ValueError("Página de blob corrupta")
            chunks.append(raw[BLOB_HEADER.size:BLOB_HEADER.size + length])
            page = nxt
        return b"".join(chunks)

    def close(self):
        self.disk.close()
