"""Extensión descendente de la gramática P1. Nunca evalúa código del usuario."""
import json
import re
from backend.core.query_engine.parser import SQLParser
from backend.core.query_engine.tokenizer import tokenize


class MultimodalSQL(SQLParser):
    @staticmethod
    def handles(sql):
        tokens = tokenize(sql)
        values = [value.upper() for kind, value in tokens if kind != "STRING"]
        return any(v in values for v in ("MATCH", "WITHIN_RADIUS", "COSINE_SCORE", "<=>", "<->", "RTREE", "INVERTED", "IVF", "SET", "LIMIT", "ORDER"))

    def parse(self, sql):
        self.tokens, self.position = tokenize(sql), 0
        command = self._take()[1].upper()
        query = {"kind": command}
        if command == "SET":
            self._expect("IVF")
            self._expect(".")
            self._expect("PROBES")
            self._expect("=")
            query["probes"] = self._literal()
            if type(query["probes"]) is not int or not 1 <= query["probes"] <= 10000:
                raise ValueError("probes debe ser un entero entre 1 y 10000")
        elif command == "CREATE":
            self._expect("INDEX")
            query["name"] = self._identifier()
            self._expect("ON")
            query["table"] = self._identifier()
            self._expect("(")
            query["column"] = self._identifier()
            self._expect(")")
            self._expect("USING")
            query["index_kind"] = self._take()[1].upper()
            if query["index_kind"] not in ("RTREE", "INVERTED", "IVF"):
                raise ValueError("Índice multimodal no soportado")
            query["options"] = {}
            if self._peek("WITH"):
                self._take()
                self._expect("(")
                while True:
                    key = self._identifier()
                    self._expect("=")
                    if key in query["options"]:
                        raise ValueError("Opción repetida")
                    query["options"][key] = self._literal()
                    if not self._peek(","):
                        break
                    self._take()
                self._expect(")")
        elif command == "SELECT":
            query.update(projection=[], conditions=[], text=None, radius=None, vector=None, order=None, limit=20)
            if self._peek("*"):
                self._take()
                query["projection"] = ["*"]
            else:
                while True:
                    name = self._identifier()
                    if name == "cosine_score":
                        self._expect("(")
                        self._expect(")")
                        self._expect("AS")
                        name = self._identifier()
                        query["score_alias"] = name
                    elif self._peek("<=>") or self._peek("<->"):
                        op = self._take()[1]
                        if name != "embedding" or query["vector"] is not None:
                            raise ValueError("Se admite una distancia sobre embedding")
                        value = self._literal()
                        if not isinstance(value, str):
                            raise ValueError("El vector se escribe como '[0.1, ...]' sin puntos suspensivos")
                        try:
                            query["vector"] = json.loads(value)
                        except json.JSONDecodeError as error:
                            raise ValueError("Vector JSON inválido") from error
                        if not isinstance(query["vector"], list) or not all(type(v) in (int, float) for v in query["vector"]):
                            raise ValueError("El vector debe ser un arreglo de números")
                        query["metric"] = "COSINE" if op == "<=>" else "L2"
                        self._expect("AS")
                        name = self._identifier()
                        query["distance_alias"] = name
                    query["projection"].append(name)
                    if not self._peek(","):
                        break
                    self._take()
            self._expect("FROM")
            query["table"] = self._identifier()
            if self._peek("WHERE"):
                self._take()
                while True:
                    column = self._identifier()
                    op = self._take()[1].upper()
                    if op == "MATCH":
                        if column != "cuerpo" or query["text"] is not None:
                            raise ValueError("MATCH se aplica una vez a cuerpo")
                        query["text"] = self._literal()
                        if not isinstance(query["text"], str) or not query["text"].strip():
                            raise ValueError("MATCH requiere una cadena")
                    elif op == "WITHIN_RADIUS":
                        if column != "ubicacion" or query["radius"] is not None:
                            raise ValueError("WITHIN_RADIUS se aplica una vez a ubicacion")
                        self._expect("(")
                        self._expect("(")
                        lon = self._literal()
                        self._expect(",")
                        lat = self._literal()
                        self._expect(")")
                        self._expect(",")
                        radius = self._literal()
                        self._expect(")")
                        if not all(type(v) in (int, float) for v in (lon, lat, radius)):
                            raise ValueError("Radio y coordenadas deben ser numéricos")
                        query["radius"] = (lon, lat, radius)
                    elif op in ("=", "<=", ">=", "<", ">", "!=", "<>"):
                        query["conditions"].append((column, op, self._literal()))
                    else:
                        raise ValueError("Predicado multimodal no soportado")
                    if not self._peek("AND"):
                        break
                    self._take()
            if self._peek("ORDER"):
                self._take()
                self._expect("BY")
                name = self._identifier()
                direction = self._take()[1].upper()
                if direction not in ("ASC", "DESC"):
                    raise ValueError("ORDER BY requiere ASC o DESC")
                query["order"] = (name, direction)
            if self._peek("LIMIT"):
                self._take()
                query["limit"] = self._literal()
                if type(query["limit"]) is not int or not 1 <= query["limit"] <= 1000:
                    raise ValueError("LIMIT debe estar entre 1 y 1000")
        else:
            raise ValueError("Sentencia multimodal no soportada")
        if self._peek(";"):
            self._take()
        if self.position != len(self.tokens):
            raise ValueError("Sintaxis no soportada o más de una sentencia")
        return query
