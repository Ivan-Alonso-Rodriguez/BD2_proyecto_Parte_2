"""SQL -> Parser -> Planner -> estructuras en disco -> resultados y métricas."""

import operator
import time
from dataclasses import asdict, dataclass, field
from backend.core.catalog.schema_manager import SchemaManager, TableDef, IndexDef
from backend.core.catalog.table_storage import TableStorage
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.page import Page
from backend.core.storage.record_serializer import RecordSerializer, KeyCodec
from .parser import SQLParser
from .planner import QueryPlanner, AccessPath
from .execution_plan import describe_plan, operation_plan

COMPARE = {
    "=": operator.eq,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "!=": operator.ne,
    "<>": operator.ne,
}


@dataclass
class QueryResult:
    rows: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    total_rows: int = 0
    affected_rows: int = 0
    offset: int = 0
    limit: int = 100
    access_path: str = ""
    index_name: str | None = None
    disk_reads: int = 0
    disk_writes: int = 0
    parse_time_ms: float = 0
    exec_time_ms: float = 0
    message: str = ""
    execution_plan: dict | None = None
    io_breakdown: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class QueryExecutor:
    def __init__(
        self,
        schema_manager=None,
        planner=None,
        directory="data/database",
        page_size=4096,
    ):
        self.schema_manager = schema_manager or SchemaManager(directory)
        self.planner = planner or QueryPlanner(self.schema_manager)
        self.page_size = page_size
        self.counter = DiskCounter()
        from backend.core.multimodal.collection import MultimodalCollection
        self.multimodal = MultimodalCollection(self)

    # PARTE IMPORTANTE PARA EXPOSICION: EJECUCION DEL PLAN Y METRICAS
    def execute(self, sql, offset=0, limit=100):
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("Paginación inválida: offset >= 0 y limit entre 1 y 1000")
        from backend.core.multimodal.sql import MultimodalSQL
        if MultimodalSQL.handles(sql):
            return self.multimodal.execute(sql, offset, limit)
        self.counter.reset()
        start = time.perf_counter()
        query = SQLParser().parse(sql)
        if self.multimodal.ready and query.table == self.multimodal.manifest()["table"] and query.kind in ("INSERT", "DELETE", "DROP_TABLE"):
            raise ValueError("Colección multimodal publicada de solo lectura; reconstruye en otro directorio para mantener todos sus índices consistentes")
        parsed = time.perf_counter()
        result = QueryResult(offset=offset, limit=limit)
        if query.kind == "CREATE_TABLE":
            self._create_table(query)
            result.access_path, result.message = (
                "CreateTable",
                f"Tabla {query.table} creada",
            )
        elif query.kind == "CREATE_INDEX":
            self._create_index(query)
            result.access_path, result.message = (
                "CreateIndex",
                f"Índice {query.index_name} construido",
            )
        elif query.kind == "DROP_TABLE":
            self.schema_manager.drop_table(query.table)
            result.access_path, result.message = (
                "DropTable",
                f"Tabla {query.table} eliminada",
            )
        else:
            table = self.schema_manager.get_table(query.table)
            with TableStorage(self.schema_manager, table, self.counter) as storage:
                if query.kind == "INSERT":
                    storage.insert(query.values)
                    result.access_path, result.affected_rows = "Insert", 1
                else:
                    self._validate_conditions(query, table)
                    plan = self.planner.choose_access_path(query)
                    result.access_path = plan.access_path.value
                    result.index_name = plan.index.name if plan.index else None
                    if query.kind == "SELECT":
                        if query.projection == ["*"]:
                            result.columns = [c.name for c in table.columns]
                        else:
                            result.columns = [
                                table.column(c).name for c in query.projection
                            ]
                    examined = matched = 0
                    for rid, raw in self._candidates(storage, plan, query):
                        examined += 1
                        row = storage.serializer.unpack(raw)
                        if not all(
                            COMPARE[c.operator](row[c.column], c.value)
                            for c in query.conditions
                        ):
                            continue
                        matched += 1
                        if query.kind == "DELETE":
                            result.affected_rows += storage.delete(rid, raw)
                        else:
                            if offset <= result.total_rows < offset + limit:
                                result.rows.append({c: row[c] for c in result.columns})
                            result.total_rows += 1
                    result.execution_plan = describe_plan(query, table, plan, {
                        "examined": examined, "matched": matched,
                        "returned": len(result.rows), "affected": result.affected_rows,
                    })
        result.parse_time_ms = (parsed - start) * 1000
        result.exec_time_ms = (time.perf_counter() - parsed) * 1000
        result.disk_reads, result.disk_writes = (
            self.counter.disk_reads,
            self.counter.disk_writes,
        )
        if not result.message:
            result.message = (
                f"{result.total_rows} filas encontradas"
                if query.kind == "SELECT"
                else f"{result.affected_rows} filas eliminadas"
                if query.kind == "DELETE"
                else f"{result.affected_rows} filas afectadas"
            )
        if result.execution_plan is None:
            result.execution_plan = operation_plan(
                query.kind, query.table, result.access_path, result.message,
                result.affected_rows if query.kind == "INSERT" else None,
            )
        result.execution_plan.update(sql=sql, metrics={
            "disk_reads": result.disk_reads, "disk_writes": result.disk_writes,
            "parse_time_ms": result.parse_time_ms, "exec_time_ms": result.exec_time_ms,
        })
        result.io_breakdown = self.counter.breakdown()
        return result

    def explain(self, sql, offset=0, limit=100):
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("Paginación inválida")
        query = SQLParser().parse(sql)
        if query.kind not in ("SELECT", "DELETE"):
            raise ValueError("Ver plan admite SELECT y DELETE; no ejecuta la sentencia")
        table = self.schema_manager.get_table(query.table)
        self._validate_conditions(query, table)
        if query.projection != ["*"]:
            for column in query.projection:
                table.column(column)
        plan = self.planner.choose_access_path(query)
        description = describe_plan(query, table, plan)
        description.update(sql=sql, metrics=None)
        return description

    def _validate_conditions(self, query, table):
        for condition in query.conditions:
            column = table.column(condition.column)
            codec = KeyCodec(column.dtype)
            condition.value = codec.unpack(codec.pack(condition.value))

    def _candidates(self, storage, plan, query):
        if plan.access_path == AccessPath.INDEX_SCAN:
            index = storage.indexes[plan.index.name]
            rids = (
                index.iter_search(plan.equality)
                if plan.index.kind == "HASH"
                else index.range_search(plan.equality, plan.equality)
            )
            yield from storage.fetch_rids(rids)
        elif plan.access_path == AccessPath.INDEX_RANGE_SCAN:
            rids = storage.indexes[plan.index.name].range_search(plan.lower, plan.upper)
            yield from storage.fetch_rids(rids)
        else:
            # Sequential puede acotar su principal por la PK aun sin índice secundario.
            bounds = [
                c for c in query.conditions if c.column == storage.table.primary_key
            ]
            if storage.table.organization == "SEQUENTIAL" and bounds:
                equal = next((c.value for c in bounds if c.operator == "="), None)
                lowers = [c.value for c in bounds if c.operator in (">", ">=")]
                uppers = [c.value for c in bounds if c.operator in ("<", "<=")]
                low = equal if equal is not None else (max(lowers) if lowers else None)
                high = equal if equal is not None else (min(uppers) if uppers else None)
                yield from storage.records.range_search(low, high)
            else:
                yield from storage.records.scan()

    def _create_table(self, query):
        if query.table in self.schema_manager.tables:
            raise ValueError(f"Tabla existente: {query.table}")
        table = TableDef(
            query.table,
            query.columns,
            query.organization,
            filename=query.table + ".bin",
            page_size=self.page_size,
        )
        self.schema_manager.validate(table)
        size = RecordSerializer(table.columns).record_size
        Page(1, size, self.page_size)
        primary = IndexDef(
            "__pk_" + table.name,
            table.primary_key,
            "HASH",
            table.name + ".__pk.idx",
            True,
        )
        table.indexes.append(primary)
        # No reutilizar un archivo huérfano de otra creación fallida.
        if (self.schema_manager.directory / table.filename).exists():
            raise ValueError(
                "Ya existe el archivo de datos; use otro nombre o directorio"
            )
        with TableStorage(self.schema_manager, table, self.counter):
            self.schema_manager.create_table(table)

    def _build_index(self, storage, definition):
        temp_definition = IndexDef(
            definition.name,
            definition.column,
            definition.kind,
            definition.filename + ".building",
            definition.internal,
        )
        path = self.schema_manager.directory / temp_definition.filename
        for item in (path, path.with_name(path.name + ".dir")):
            if item.exists():
                item.unlink()
        index = storage.open_index(temp_definition)
        try:
            column_position = [c.name for c in storage.table.columns].index(
                definition.column
            )
            for rid, raw in storage.records.scan():
                index.insert(storage.serializer.field_value(raw, column_position), rid)
        finally:
            index.close()
        destination = self.schema_manager.directory / definition.filename
        path.replace(destination)
        if definition.kind == "HASH":
            path.with_name(path.name + ".dir").replace(
                destination.with_name(destination.name + ".dir")
            )

    def _create_index(self, query):
        self.schema_manager.check_index_name(query.index_name)
        table = self.schema_manager.get_table(query.table)
        table.column(query.index_column)
        definition = IndexDef(
            query.index_name,
            query.index_column,
            query.index_kind,
            table.name + "." + query.index_name + ".idx",
        )
        with TableStorage(self.schema_manager, table, self.counter) as storage:
            self._build_index(storage, definition)
        self.schema_manager.add_index(table.name, definition)

    def reorganize(self, table_name):
        table = self.schema_manager.get_table(table_name)
        if table.organization != "SEQUENTIAL":
            raise ValueError("Solo se reorganizan tablas SEQUENTIAL")
        self.counter.reset()
        start = time.perf_counter()
        with TableStorage(self.schema_manager, table, self.counter) as storage:
            storage.records.reorganize()
            for index in storage.indexes.values():
                index.close()
            for definition in table.indexes:
                self._build_index(storage, definition)
        return QueryResult(
            access_path="Reorganize",
            affected_rows=storage.records.count,
            disk_reads=self.counter.disk_reads,
            disk_writes=self.counter.disk_writes,
            exec_time_ms=(time.perf_counter() - start) * 1000,
            message="Principal reorganizado e índices reconstruidos",
        )

    def list_tables(self):
        return [asdict(table) for table in self.schema_manager.tables.values()]
