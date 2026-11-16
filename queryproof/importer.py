"""Strict, in-memory CSV imports. Files never name paths on the server."""
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
TYPE = re.compile(r"^(VARCHAR|INTEGER|BIGINT|DOUBLE|BOOLEAN|DATE|TIMESTAMP|DECIMAL(?:\((\d+),(\d+)\))?)$")
MAX_BYTES = 100 * 1024 * 1024
MAX_ROWS = 1_000_000


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid identifier: {value!r}. Use letters, digits and underscores.")
    return value


def _value(raw, kind):
    if raw == "":
        return None
    if kind in ("INTEGER", "BIGINT"):
        value = int(raw)
        low, high = (-2**31, 2**31 - 1) if kind == "INTEGER" else (-2**63, 2**63 - 1)
        if not low <= value <= high:
            raise ValueError("integer out of range")
        return value
    if kind == "DOUBLE" or kind.startswith("DECIMAL"):
        value = Decimal(raw)
        if not value.is_finite():
            raise ValueError("non-finite number")
        if kind.startswith("DECIMAL"):
            match = TYPE.fullmatch(kind)
            precision, scale = (int(match[2]), int(match[3])) if match[2] else (18, 3)
            if not 0 <= scale <= precision <= 38:
                raise ValueError("invalid decimal precision/scale")
            if value != value.quantize(Decimal(1).scaleb(-scale)) or abs(value) >= Decimal(10) ** (precision - scale):
                raise ValueError("value cannot be represented exactly in declared decimal type")
            return format((abs(value) if value == 0 else value).quantize(Decimal(1).scaleb(-scale)), "f")
        return float(value)
    if kind in ("DATE", "TIMESTAMP"):
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is not None:
            raise ValueError("use timezone-naive UTC timestamps")
        return parsed.date().isoformat() if kind == "DATE" else parsed.isoformat(sep=" ")
    if kind == "BOOLEAN":
        if raw.lower() not in ("true", "false"):
            raise ValueError("expected true or false")
        return raw.lower() == "true"
    return raw


def _import_bundle(bundle):
    if not isinstance(bundle, dict) or not isinstance(bundle.get("manifest"), dict) or not isinstance(bundle.get("files"), dict):
        raise ValueError("A bundle needs a JSON manifest and a files map containing CSV text.")
    manifest, files = bundle["manifest"], bundle["files"]
    tables = manifest.get("tables")
    if not isinstance(tables, list) or not 1 <= len(tables) <= 5:
        raise ValueError("Import between 1 and 5 tables.")
    if any(not isinstance(v, str) for v in files.values()):
        raise ValueError("Each file must contain CSV text.")
    input_bytes = sum(len(v.encode("utf-8")) for v in files.values())
    if input_bytes > MAX_BYTES:
        raise ValueError("CSV input exceeds the 100 MB limit.")
    result = {}
    count = 0
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("Each table must be an object.")
        name = identifier(table.get("name"))
        if name.casefold() in {key.casefold() for key in result}:
            raise ValueError(f"Duplicate table: {name}")
        filename = table.get("file")
        if not isinstance(filename, str) or filename not in files:
            raise ValueError(f"Missing CSV for {name}.")
        columns = table.get("columns")
        if not isinstance(columns, list) or not columns or len(columns) > 100:
            raise ValueError(f"{name}: declare between 1 and 100 columns.")
        names = []
        for column in columns:
            if not isinstance(column, dict):
                raise ValueError(f"{name}: invalid column declaration.")
            col = identifier(column.get("name"))
            kind = column.get("type")
            if col.casefold() in {v.casefold() for v in names} or not isinstance(kind, str) or not TYPE.fullmatch(kind):
                raise ValueError(f"{name}.{col}: duplicate column or unsupported type.")
            names.append(col)
        reader = csv.DictReader(io.StringIO(files[filename]), strict=True)
        if reader.fieldnames != names:
            raise ValueError(f"{name}: CSV headers must match declared columns in order: {', '.join(names)}")
        rows = []
        try:
            for line, row in enumerate(reader, 2):
                count += 1
                if count > MAX_ROWS:
                    raise ValueError("Import exceeds the 1 million row limit.")
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{name}, line {line}: wrong number of fields.")
                try:
                    rows.append({column["name"]: _value(row[column["name"]], column["type"]) for column in columns})
                except (ValueError, InvalidOperation) as error:
                    raise ValueError(f"{name}, line {line}: {error}") from error
        except csv.Error as error:
            raise ValueError(f"{name}: invalid CSV: {error}") from error
        result[name] = {"columns": columns, "rows": rows, "row_count": len(rows)}
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"id": hashlib.sha256(canonical.encode()).hexdigest(), "name": str(manifest.get("name", "Imported analysis"))[:200], "tables": result, "row_count": count, "input_bytes": input_bytes}


def import_bundle(bundle):
    with localcontext() as context:
        context.prec = 60
        return _import_bundle(bundle)
