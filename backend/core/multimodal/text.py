"""Diccionario ordenado, posteos y normas L2 persistidos en páginas de 4 KB."""
import heapq
import math
import re
import struct
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from nltk.stem.snowball import SnowballStemmer
from .paged import FixedArray, PAGE_SIZE

VOCAB_FORMAT = "<128sQQQ"
POSTING_FORMAT = "<QI"


class Analyzer:
    def __init__(self, language="english"):
        if language not in ("english", "spanish"):
            raise ValueError("Idioma debe ser english o spanish")
        self.language = language
        self.stemmer = SnowballStemmer(language)
        root = Path(__file__).parent / "stopwords"
        self.stopwords = set()
        for name in ("es", "en"):
            self.stopwords.update((root / f"stoplist_{name}.txt").read_text(encoding="utf-8").split())

    def tokens(self, text):
        text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
        return [self.stemmer.stem(t) for t in re.findall(r"[a-z0-9]+", text) if t not in self.stopwords]


def merge(a, b, operation):
    """Mezcla O(n+m), sin intersección/unión de sets para la recuperación booleana."""
    result, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            if operation != "NOT":
                result.append(a[i])
            i, j = i+1, j+1
        elif a[i] < b[j]:
            if operation in ("OR", "NOT"):
                result.append(a[i])
            i += 1
        else:
            if operation == "OR":
                result.append(b[j])
            j += 1
    if operation in ("OR", "NOT"):
        result.extend(a[i:])
    if operation == "OR":
        result.extend(b[j:])
    return result


class InvertedIndex:
    def __init__(self, directory, counter=None):
        root = Path(directory)
        self.vocab = FixedArray(root / "vocab.dic", VOCAB_FORMAT, counter)
        self.postings = FixedArray(root / "postings.inv", POSTING_FORMAT, counter)
        self.norms = FixedArray(root / "norms.norm", "<Qd", counter)
        raw = self.vocab.disk.read_page(0)
        self.n, lang = struct.unpack_from("<Q16s", raw, 32)
        self.analyzer = Analyzer(lang.rstrip(b"\0").decode() or "english")
        self.last_candidates = 0

    @classmethod
    def build(cls, directory, documents, counter=None, language="english"):
        """Construcción en RAM explícita; las consultas solo leen términos solicitados.

        documents: iterable (doc_id/RID empaquetado, texto o Counter de palabras visuales).
        """
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if any((root / name).exists() for name in ("vocab.dic", "postings.inv", "norms.norm")):
            raise ValueError("El directorio del índice debe estar vacío")
        analyzer, lists, ids = Analyzer(language), defaultdict(list), set()
        for doc_id, text in documents:
            if doc_id in ids:
                raise ValueError("doc_id duplicado")
            ids.add(doc_id)
            counts = Counter(analyzer.tokens(text)) if isinstance(text, str) else Counter(text)
            for term, tf in counts.items():
                if len(term.encode()) > 127 or not isinstance(tf, int) or tf <= 0:
                    raise ValueError("Término o frecuencia inválida")
                lists[term].append((doc_id, tf))
        n, squared, vocab_rows, posting_rows = len(ids), defaultdict(float), [], []
        postings = FixedArray(root / "postings.inv", POSTING_FORMAT, counter)
        vocab = FixedArray(root / "vocab.dic", VOCAB_FORMAT, counter)
        norms = FixedArray(root / "norms.norm", "<Qd", counter)
        try:
            for term in sorted(lists):
                rows = sorted(lists[term])
                df = len(rows)
                start = len(posting_rows)
                offset = PAGE_SIZE + (start // postings.capacity)*PAGE_SIZE + (start % postings.capacity)*postings.codec.size
                vocab_rows.append((term.encode(), df, offset, df))
                idf = math.log10(n / df)
                for doc_id, tf in rows:
                    squared[doc_id] += ((1+math.log10(tf))*idf)**2
                posting_rows.extend(rows)
            postings.write_all(posting_rows)
            vocab.write_all(vocab_rows)
            norms.write_all((doc_id, math.sqrt(squared[doc_id])) for doc_id in sorted(ids))
            raw = bytearray(vocab.disk.read_page(0))
            struct.pack_into("<Q16s", raw, 32, n, language.encode())
            vocab.disk.write_page(0, bytes(raw))
        finally:
            vocab.close()
            postings.close()
            norms.close()
        return cls(root, counter)

    def term(self, term):
        row = self.vocab.find(term.encode().ljust(128, b"\0"))
        if row is None:
            return []
        _, df, offset, length = row
        page, inner = divmod(offset, PAGE_SIZE)
        start = (page-1)*self.postings.capacity + inner//self.postings.codec.size
        if df != length or start+length > self.postings.count:
            raise ValueError("Lista de posteo corrupta")
        return [self.postings.get(i) for i in range(start, start+length)]

    def boolean(self, expression):
        tokens = re.findall(r"AND-NOT|[\w]+|[()]", expression, re.UNICODE | re.IGNORECASE)
        if not tokens:
            raise ValueError("Consulta booleana vacía")
        position = 0
        def peek(value):
            return position < len(tokens) and tokens[position].upper() == value
        def atom():
            nonlocal position
            if peek("NOT"):
                position += 1
                return merge([r[0] for r in self.norms.rows()], atom(), "NOT")
            if peek("("):
                position += 1
                result = disjunction()
                if not peek(")"):
                    raise ValueError("Falta cerrar paréntesis booleano")
                position += 1
                return result
            if position >= len(tokens) or tokens[position].upper() in ("AND", "OR", "AND-NOT", ")"):
                raise ValueError("Se esperaba un término booleano")
            terms = self.analyzer.tokens(tokens[position])
            position += 1
            return [r[0] for r in self.term(terms[0])] if terms else []
        def conjunction():
            nonlocal position
            result = atom()
            while peek("AND") or peek("AND-NOT"):
                operation = tokens[position].upper()
                position += 1
                if operation == "AND-NOT" or peek("NOT"):
                    if operation != "AND-NOT":
                        position += 1
                    result = merge(result, atom(), "NOT")
                else:
                    result = merge(result, atom(), "AND")
            return result
        def disjunction():
            nonlocal position
            result = conjunction()
            while peek("OR"):
                position += 1
                result = merge(result, conjunction(), "OR")
            return result
        result = disjunction()
        if position != len(tokens):
            raise ValueError("Falta un operador AND/OR entre términos")
        return result

    def rank(self, query, k=10, allowed=None, boolean=False, exclude=None):
        if k < 1:
            raise ValueError("k debe ser positivo")
        if boolean:
            matches = set(self.boolean(query))
            allowed = matches if allowed is None else matches & allowed
            # Los operadores booleanos no forman parte del vocabulario de consulta.
            query = re.sub(r"\b(?:AND|OR|NOT)\b|[()]", " ", query, flags=re.I)
        counts = Counter(self.analyzer.tokens(query)) if isinstance(query, str) else Counter(query)
        scores, qnorm = defaultdict(float), 0.
        for term, tfq in counts.items():
            rows = self.term(term)
            if not rows:
                continue
            idf = math.log10(self.n / len(rows))
            qw = (1+math.log10(tfq))*idf
            qnorm += qw*qw
            for doc_id, tf in rows:
                if doc_id != exclude and (allowed is None or doc_id in allowed):
                    scores[doc_id] += qw*(1+math.log10(tf))*idf
        qnorm = math.sqrt(qnorm)
        self.last_candidates = len(scores)
        self.last_matches = 0
        def normalized():
            for doc_id, dot in scores.items():
                norm = self.norms.find(doc_id)[1]
                if dot > 0 and norm and qnorm:
                    self.last_matches += 1
                    yield doc_id, min(1., dot/(norm*qnorm))
        return heapq.nsmallest(k, normalized(), key=lambda x: (-x[1], x[0]))

    def close(self):
        self.vocab.close()
        self.postings.close()
        self.norms.close()
