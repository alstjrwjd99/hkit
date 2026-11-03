"""Profile a local CSV/TSV and optionally write a draft data contract."""

import argparse
from collections import Counter
import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
from itertools import islice
import json
from pathlib import Path
import re


NUMBER = re.compile(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ].*)?\Z")


def date_is_valid(value, date_format):
    try:
        if date_format != "iso8601":
            datetime.strptime(value, date_format)
        elif len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


@dataclass
class ColumnStats:
    date_format: str | None = None
    missing: int = 0
    types: Counter = field(default_factory=Counter)
    values: set = field(default_factory=set)
    numeric_min: Decimal | None = None
    numeric_max: Decimal | None = None
    date_valid: int = 0
    date_invalid: int = 0

    def observe(self, raw):
        value = raw.strip()
        if not value:
            self.missing += 1
            return
        self.values.add(raw)
        if self.date_format or ISO_DATE.fullmatch(value):
            valid = date_is_valid(value, self.date_format or "iso8601")
            self.date_valid += valid
            self.date_invalid += not valid
            kind = "date" if valid else "string"
        elif value.lower() in {"true", "false"}:
            kind = "boolean"
        elif NUMBER.fullmatch(value):
            try:
                number = Decimal(value)
                kind = "integer" if re.fullmatch(r"[+-]?[0-9]+", value) else "number"
                self.numeric_min = number if self.numeric_min is None else min(self.numeric_min, number)
                self.numeric_max = number if self.numeric_max is None else max(self.numeric_max, number)
            except InvalidOperation:
                kind = "string"
        else:
            kind = "string"
        self.types[kind] += 1

    def summary(self, rows):
        types = set(self.types)
        inferred = "unknown"
        if types:
            inferred = next(iter(types)) if len(types) == 1 else "mixed"
            if types == {"integer", "number"}:
                inferred = "number"
        return {
            "inferred_type": inferred,
            "type_counts": dict(self.types),
            "non_missing": rows - self.missing,
            "missing": self.missing,
            "missing_rate": self.missing / rows if rows else None,
            "distinct_non_missing": len(self.values),
            "numeric_range": (
                {"min": str(self.numeric_min), "max": str(self.numeric_max)}
                if self.numeric_min is not None else None
            ),
            "date_validation": {
                "format": self.date_format or "iso8601",
                "scope": "all_non_missing" if self.date_format else "iso_looking_values",
                "valid": self.date_valid,
                "invalid": self.date_invalid,
            },
            "unique_non_missing_candidate": rows > 0 and self.missing == 0 and len(self.values) == rows,
        }


def profile(path, delimiter, *, encoding="utf-8-sig", keys=(), dates=None, max_rows=None):
    dates = dates or {}
    with path.open(encoding=encoding, newline="") as source:
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        header = next(reader, None)
        if not header or any(not name.strip() for name in header):
            raise ValueError("expected a header with nonempty column names")
        if len(set(header)) != len(header):
            raise ValueError("duplicate column names in header")
        requested = set(dates).union(name for key in keys for name in key)
        if requested.difference(header):
            raise ValueError("unknown columns: " + ", ".join(sorted(requested.difference(header))))
        columns = {name: ColumnStats(dates.get(name)) for name in header}
        key_indexes = [[header.index(name) for name in key] for key in keys]
        key_values = [set() for key in keys]
        key_missing = [0] * len(keys)
        key_duplicates = [0] * len(keys)
        seen = set()
        valid = wrong_width = duplicates = 0
        for row in islice(reader, max_rows):
            if len(row) != len(header):
                wrong_width += 1
                continue
            valid += 1
            row_key = tuple(row)
            if row_key in seen:
                duplicates += 1
            seen.add(row_key)
            for name, value in zip(header, row):
                columns[name].observe(value)
            for i, indexes in enumerate(key_indexes):
                key = tuple(row[index] for index in indexes)
                if any(not value.strip() for value in key):
                    key_missing[i] += 1
                else:
                    key_duplicates[i] += key in key_values[i]
                    key_values[i].add(key)

    return {
        "records": valid + wrong_width,
        "valid_width": valid,
        "wrong_width": wrong_width,
        "duplicate_rows_after_first": duplicates,
        "missing_in_valid_rows": {name: stats.missing for name, stats in columns.items()},
        "encoding": encoding,
        "complete_scan": max_rows is None or valid + wrong_width < max_rows,
        "columns": {name: stats.summary(valid) for name, stats in columns.items()},
        "keys": [
            {"columns": list(key), "missing_rows": key_missing[i],
             "duplicate_rows_after_first": key_duplicates[i],
             "unique_non_missing_candidate": valid > 0 and not key_missing[i] and not key_duplicates[i]}
            for i, key in enumerate(keys)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--key", action="append", default=[], metavar="COL1,COL2")
    parser.add_argument("--date", action="append", default=[], metavar="COLUMN=FORMAT")
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--contract-out", type=Path)
    parser.add_argument("--prd-revision", default="")
    args = parser.parse_args()
    if args.max_rows is not None and args.max_rows < 1:
        parser.error("--max-rows must be positive")
    dates = {}
    for entry in args.date:
        name, separator, fmt = entry.partition("=")
        if not separator or not name or not fmt:
            parser.error("--date requires COLUMN=FORMAT")
        dates[name] = fmt
    keys = [key.split(",") for key in args.key]
    if any(not name or len(set(key)) != len(key) for key in keys for name in key):
        parser.error("--key requires distinct, nonempty column names")
    delimiter = "\t" if args.path.suffix.lower() == ".tsv" else ","
    try:
        before = args.path.stat()
        result = profile(args.path, delimiter, encoding=args.encoding, keys=keys,
                         dates=dates, max_rows=args.max_rows)
        if args.contract_out:
            with args.path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            after = args.path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("input changed during profiling; rerun against a stable input")
            contract = {
                "schema_version": 1,
                "status": "draft",
                "revision": "",
                "prd_revision": args.prd_revision,
                "source": {"path": str(args.path), "sha256": digest, "delimiter": delimiter},
                "observations": result,
                "constraints": [],
            }
            with args.contract_out.open("x", encoding="utf-8") as output:
                json.dump(contract, output, ensure_ascii=False, indent=2)
                output.write("\n")
    except UnicodeDecodeError as error:
        parser.exit(1, f"encoding error ({args.encoding}): {error}. Check --encoding, for example cp949.\n")
    except LookupError as error:
        parser.exit(1, f"encoding configuration error: {error}\n")
    except FileExistsError:
        parser.exit(1, "contract output already exists; choose a new revision path\n")
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"input or output error: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
