"""Contador de transferencias completas; no estima costos ni fallos de caché del SO."""


class DiskCounter:
    # PARTE IMPORTANTE PARA EXPOSICION: I/O CONTADO, NO ESTIMADO
    def __init__(self):
        self.reset()

    def register_read(self, kind="other"):
        self.disk_reads += 1
        self.by_kind.setdefault(kind, [0, 0])[0] += 1

    def register_write(self, kind="other"):
        self.disk_writes += 1
        self.by_kind.setdefault(kind, [0, 0])[1] += 1

    def reset(self):
        self.disk_reads = 0
        self.disk_writes = 0
        self.by_kind = {}

    def breakdown(self):
        return {key: {"disk_reads": value[0], "disk_writes": value[1]}
                for key, value in self.by_kind.items()}

    def snapshot(self):
        return {"disk_reads": self.disk_reads, "disk_writes": self.disk_writes}
