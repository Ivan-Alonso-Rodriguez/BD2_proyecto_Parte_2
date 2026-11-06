import hashlib
import io
import json
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data import fetch_fashion


def parquet_bytes(tmp_path):
    path = tmp_path / "valid.parquet"
    pq.write_table(pa.table({"id": [1, 2]}), path)
    return path.read_bytes()


def response(body, length=None):
    stream = io.BytesIO(body)
    stream.headers = {"Content-Length": str(len(body) if length is None else length)}
    return stream


def test_valid_cache_does_not_download(tmp_path, monkeypatch):
    body = parquet_bytes(tmp_path)
    target = tmp_path / "fashion.parquet"
    target.write_bytes(body)
    (tmp_path / "source.json").write_text(json.dumps({
        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["fetch_fashion.py", "--output", str(tmp_path)])
    monkeypatch.setattr(fetch_fashion, "urlopen", lambda *a, **k: pytest.fail("Unexpected download"))

    fetch_fashion.main()

    assert target.read_bytes() == body


@pytest.mark.parametrize("problem", ["null_metadata", "wrong_checksum", "damaged_footer"])
def test_bad_cache_is_replaced_with_valid_download(tmp_path, monkeypatch, problem):
    body = parquet_bytes(tmp_path)
    cached = body[:-4] + b"\0" * 4 if problem == "damaged_footer" else body
    target = tmp_path / "fashion.parquet"
    source_path = tmp_path / "source.json"
    target.write_bytes(cached)
    metadata = {"bytes": len(cached), "sha256": hashlib.sha256(cached).hexdigest()}
    if problem == "wrong_checksum":
        metadata["sha256"] = "0" * 64
    source_path.write_text("\0" * 500 if problem == "null_metadata" else json.dumps(metadata), encoding="utf-8")
    responses = iter([response(b'{"sha": "test-revision"}'), response(body)])
    monkeypatch.setattr(fetch_fashion, "urlopen", lambda *a, **k: next(responses))
    monkeypatch.setattr(sys, "argv", ["fetch_fashion.py", "--output", str(tmp_path)])

    fetch_fashion.main()

    fetch_fashion.validate_cache(target, source_path)
    assert target.read_bytes() == body
    assert json.loads(source_path.read_text())["revision"] == "test-revision"


@pytest.mark.parametrize("length", [10, 100])
def test_bad_download_preserves_existing_file(tmp_path, monkeypatch, length):
    target = tmp_path / "fashion.parquet"
    target.write_bytes(b"previous dataset")
    monkeypatch.setattr(fetch_fashion, "urlopen", lambda *a, **k: response(b"notParquet", length))

    with pytest.raises(ValueError):
        fetch_fashion.download("https://example.invalid/data.parquet", target)

    assert target.read_bytes() == b"previous dataset"
