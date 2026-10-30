"""R-Tree en disco, inserción por mínima ampliación y Linear Split de Guttman.

La dimensión 2 usa float64. Dimensiones experimentales mayores usan float32
con redondeo hacia afuera de los MBR para conservar cotas inferiores seguras.
"""
import heapq
import math
import struct
from backend.core.storage.disk_manager import DiskManager
from .paged import PAGE_SIZE, pack_rid, unpack_rid

META = struct.Struct("<4sIIIIQ")
NODE = struct.Struct("<4sIBH")


def union(a, b):
    d = len(a) // 2
    return tuple(min(a[i], b[i]) for i in range(d)) + tuple(max(a[i+d], b[i+d]) for i in range(d))


def area(box):
    d = len(box) // 2
    return math.prod(max(0, box[i+d] - box[i]) for i in range(d))


def intersects(a, b):
    d = len(a) // 2
    return all(a[i] <= b[i+d] and b[i] <= a[i+d] for i in range(d))


def mindist(point, box):
    d = len(point)
    return math.sqrt(sum(max(box[i] - point[i], 0, point[i] - box[i+d])**2 for i in range(d)))


class RTree:
    def __init__(self, path, counter=None, dimensions=2, max_entries=None):
        self.disk = DiskManager(path, counter=counter)
        if self.disk.num_pages():
            magic, version, self.d, self.root, self.capacity, self.count = META.unpack_from(self.disk.read_page(0))
            if magic != b"RTR2" or version != 1:
                self.close()
                raise ValueError("R-Tree incompatible")
        else:
            if not 2 <= dimensions <= 128:
                raise ValueError("Dimensión fuera de rango [2,128]")
            self.d, self.root, self.count = dimensions, 1, 0
            size = 2 * self.d * (8 if self.d == 2 else 4) + 8
            physical = (PAGE_SIZE - NODE.size) // size
            self.capacity = min(max_entries or physical, physical)
            if self.capacity < 3:
                raise ValueError("Capacidad insuficiente")
            self.disk.allocate_page(self._meta())
            self.disk.allocate_page(NODE.pack(b"RTN2", 1, 1, 0).ljust(PAGE_SIZE, b"\0"))
        self.entry = struct.Struct("<" + ("d" if self.d == 2 else "f") * (2*self.d) + "Q")
        self.visited = []

    def _meta(self):
        return META.pack(b"RTR2", 1, self.d, self.root, self.capacity, self.count).ljust(PAGE_SIZE, b"\0")

    def _read(self, page):
        raw = self.disk.read_page(page)
        magic, pid, leaf, count = NODE.unpack_from(raw)
        if magic != b"RTN2" or pid != page or count > self.capacity:
            raise ValueError("Nodo R-Tree corrupto")
        entries = []
        for i in range(count):
            row = self.entry.unpack_from(raw, NODE.size+i*self.entry.size)
            entries.append((row[:-1], row[-1]))
        return bool(leaf), entries

    def _write(self, page, leaf, entries):
        raw = bytearray(PAGE_SIZE)
        NODE.pack_into(raw, 0, b"RTN2", page, leaf, len(entries))
        for i, (box, ref) in enumerate(entries):
            if self.d != 2:
                import numpy as np
                lower = np.nextafter(np.asarray(box[:self.d], dtype=np.float32), np.float32(-np.inf))
                upper = np.nextafter(np.asarray(box[self.d:], dtype=np.float32), np.float32(np.inf))
                box = (*lower, *upper)
            self.entry.pack_into(raw, NODE.size+i*self.entry.size, *box, ref)
        if page == self.disk.num_pages():
            self.disk.allocate_page(bytes(raw))
        else:
            self.disk.write_page(page, bytes(raw))

    def _bounds(self, entries):
        box = entries[0][0]
        for entry in entries[1:]:
            box = union(box, entry[0])
        return box

    def _split(self, entries):
        # LinearPickSeeds: máxima separación normalizada entre extremos.
        best, seeds = -math.inf, (0, 1)
        for axis in range(self.d):
            a = max(range(len(entries)), key=lambda i: entries[i][0][axis])
            b = min(range(len(entries)), key=lambda i: entries[i][0][axis+self.d])
            width = max(e[0][axis+self.d] for e in entries) - min(e[0][axis] for e in entries)
            separation = (entries[a][0][axis] - entries[b][0][axis+self.d]) / (width or 1)
            if a != b and separation > best:
                best, seeds = separation, (a, b)
        left, right = [entries[seeds[0]]], [entries[seeds[1]]]
        pending = [e for i, e in enumerate(entries) if i not in seeds]
        minimum = max(1, math.ceil(self.capacity * .4))
        while pending:
            if len(left) + len(pending) == minimum:
                left.extend(pending)
                break
            if len(right) + len(pending) == minimum:
                right.extend(pending)
                break
            entry = pending.pop()
            a, b = self._bounds(left), self._bounds(right)
            key_a = (area(union(a, entry[0])) - area(a), area(a), len(left))
            key_b = (area(union(b, entry[0])) - area(b), area(b), len(right))
            (left if key_a <= key_b else right).append(entry)
        return left, right

    def insert(self, box, rid):
        box = tuple(float(v) for v in box)
        if len(box) != 2*self.d or not all(math.isfinite(v) for v in box) or any(box[i] > box[i+self.d] for i in range(self.d)):
            raise ValueError("MBR inválido")
        def descend(page):
            leaf, entries = self._read(page)
            if leaf:
                entries.append((box, pack_rid(rid)))
            else:
                i = min(range(len(entries)), key=lambda j: (area(union(entries[j][0], box))-area(entries[j][0]), area(entries[j][0])))
                child = entries[i][1]
                bound, sibling = descend(child)
                entries[i] = (bound, child)
                if sibling:
                    entries.append(sibling)
            if len(entries) <= self.capacity:
                self._write(page, leaf, entries)
                return self._bounds(entries), None
            left, right = self._split(entries)
            other = self.disk.num_pages()
            self._write(page, leaf, left)
            self._write(other, leaf, right)
            return self._bounds(left), (self._bounds(right), other)
        bound, sibling = descend(self.root)
        if sibling:
            root = self.disk.num_pages()
            self._write(root, False, [(bound, self.root), sibling])
            self.root = root
        self.count += 1
        self.disk.write_page(0, self._meta())

    def window(self, box):
        if len(box) != 2*self.d or not all(math.isfinite(v) for v in box) or any(box[i] > box[i+self.d] for i in range(self.d)):
            raise ValueError("Ventana inválida")
        self.visited, stack, result = [], [self.root], []
        while stack:
            page = stack.pop()
            leaf, entries = self._read(page)
            self.visited.append(page)
            for mbr, ref in entries:
                if intersects(mbr, box):
                    if leaf:
                        result.append(unpack_rid(ref))
                    else:
                        stack.append(ref)
        return result

    def knn(self, point, k=10, metric=mindist, allowed=None):
        if len(point) != self.d or k < 1 or not all(math.isfinite(v) for v in point):
            raise ValueError("Punto o k inválido")
        self.visited, queue, best = [], [(0., self.root)], []
        while queue:
            bound, page = heapq.heappop(queue)
            if len(best) == k and bound > -best[0][0]:
                break
            leaf, entries = self._read(page)
            self.visited.append(page)
            for box, ref in entries:
                distance = metric(point, box)
                if leaf:
                    if allowed is not None and ref not in allowed:
                        continue
                    item = (-distance, -ref)
                    if len(best) < k:
                        heapq.heappush(best, item)
                    elif item > best[0]:
                        heapq.heapreplace(best, item)
                elif len(best) < k or distance <= -best[0][0]:
                    heapq.heappush(queue, (distance, ref))
        return [(unpack_rid(-ref), -dist) for dist, ref in sorted(best, reverse=True)]

    def close(self):
        self.disk.close()
