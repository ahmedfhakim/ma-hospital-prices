"""
Turn any CMS hospital price file into ONE standard long table (Parquet).

CMS allows three layouts, and hospitals use all of them:
  * CSV "tall": one row per item x payer x plan
  * CSV "wide": one row per item, with a set of columns for every payer/plan
                e.g. "standard_charge|Blue Cross|PPO|negotiated_dollar"
  * JSON:       nested items -> standard_charges -> payers_information

All three become the same output grain:
  one row per item x setting x payer x plan  (payer is NULL for rows that only
  carry gross / cash prices)

CSV is parsed with DuckDB and JSON with ijson (streaming), so multi-GB files
never have to fit in memory.
"""
from __future__ import annotations

import codecs
import csv
import json
import re
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import ijson
import pyarrow as pa
import pyarrow.parquet as pq

# ----------------------------------------------------------------------------
# Output schema -- identical for every input format
# ----------------------------------------------------------------------------
CODE_TYPE = pa.struct([("code", pa.string()), ("type", pa.string())])
SCHEMA = pa.schema([
    ("description", pa.string()),
    ("codes", pa.list_(CODE_TYPE)),
    ("setting", pa.string()),
    ("modifiers", pa.string()),
    ("drug_unit", pa.string()),
    ("drug_unit_type", pa.string()),
    ("gross_charge", pa.float64()),
    ("discounted_cash", pa.float64()),
    ("min_charge", pa.float64()),
    ("max_charge", pa.float64()),
    ("payer_name", pa.string()),
    ("plan_name", pa.string()),
    ("negotiated_dollar", pa.float64()),
    ("negotiated_percentage", pa.float64()),
    ("negotiated_algorithm", pa.string()),
    ("methodology", pa.string()),
    ("median_amount", pa.float64()),      # v3 (2026): actual allowed amounts
    ("p10_amount", pa.float64()),
    ("p90_amount", pa.float64()),
    ("allowed_count", pa.string()),
    ("estimated_amount", pa.float64()),   # v2 only (replaced by the fields above)
    ("notes", pa.string()),
])
DUCK_TYPES = {
    pa.string(): "VARCHAR",
    pa.float64(): "DOUBLE",
    pa.list_(CODE_TYPE): "STRUCT(code VARCHAR, type VARCHAR)[]",
}

# CSV column (normalized) -> output column
BASE_COLUMNS = {
    "description": "description",
    "setting": "setting",
    "modifiers": "modifiers",
    "drug_unit_of_measurement": "drug_unit",
    "drug_type_of_measurement": "drug_unit_type",
    "standard_charge|gross": "gross_charge",
    "standard_charge|discounted_cash": "discounted_cash",
    "standard_charge|min": "min_charge",
    "standard_charge|max": "max_charge",
    "additional_generic_notes": "notes",
}
TALL_PAYER_COLUMNS = {
    "payer_name": "payer_name",
    "plan_name": "plan_name",
    "standard_charge|negotiated_dollar": "negotiated_dollar",
    "standard_charge|negotiated_percentage": "negotiated_percentage",
    "standard_charge|negotiated_algorithm": "negotiated_algorithm",
    "standard_charge|methodology": "methodology",
    "median_amount": "median_amount",
    "10th_percentile": "p10_amount",
    "90th_percentile": "p90_amount",
    "count": "allowed_count",
    "estimated_amount": "estimated_amount",
}
# wide columns look like  <prefix>|<payer>|<plan>[|<field>]
WIDE_PREFIX_FIELDS = {
    ("standard_charge", "negotiated_dollar"): "negotiated_dollar",
    ("standard_charge", "negotiated_percentage"): "negotiated_percentage",
    ("standard_charge", "negotiated_algorithm"): "negotiated_algorithm",
    ("standard_charge", "methodology"): "methodology",
    ("median_amount", None): "median_amount",
    ("10th_percentile", None): "p10_amount",
    ("90th_percentile", None): "p90_amount",
    ("count", None): "allowed_count",
    ("estimated_amount", None): "estimated_amount",
    ("additional_payer_notes", None): "notes",
}
NUMERIC = {f.name for f in SCHEMA if f.type == pa.float64()}


class ParseError(ValueError):
    """The file doesn't look like a CMS price file."""


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def parse_file(path: Path, hospital_id: str, out_dir: Path) -> dict:
    """Parse one price file. Writes:
         <out_dir>/charges/hospital_id=<id>/data.parquet
         <out_dir>/hospitals/<id>.json   (file-level metadata + lineage)
       Returns the metadata dict."""
    path = Path(path)
    charges_dir = out_dir / "charges" / f"hospital_id={hospital_id}"
    charges_dir.mkdir(parents=True, exist_ok=True)
    out_file = charges_dir / "data.parquet"

    if sniff_is_json(path):
        meta, rows = parse_json(path, out_file)
        fmt = "json"
    else:
        meta, rows, fmt = parse_csv(path, out_file)

    meta.update({
        "hospital_id": hospital_id,
        "source_file": path.name,
        "source_format": fmt,
        "row_count": rows,
        "parsed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    (out_dir / "hospitals").mkdir(parents=True, exist_ok=True)
    (out_dir / "hospitals" / f"{hospital_id}.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta


def sniff_is_json(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(4096).lstrip(b"\xef\xbb\xbf \t\r\n")
    return head[:1] in (b"{", b"[")


# ----------------------------------------------------------------------------
# CSV
# ----------------------------------------------------------------------------
# A double quote sitting INSIDE a quoted field without being doubled, e.g.
#   "VAGINAL DILATOR SZ4 ORNG 9"X 1"      (an inch mark)
# breaks the CSV standard. Match a quote that has a non-delimiter, non-quote
# character on BOTH sides -- a real field boundary always has a comma, a line
# break or another quote next to it.
STRAY_QUOTE = re.compile(r'(?<=[^,"\r\n])"(?=[^,"\r\n])')


def prepare_csv(path: Path) -> tuple[Path, dict]:
    """Make a CSV safe for a strict parser, without hiding what was changed.

    1. Encoding: many hospital CSVs are Windows-1252 exports from Excel, not
       UTF-8 (even CMS's own V2 example is). Decoded line by line, so a file that
       is mostly UTF-8 with a few bad bytes keeps its good lines intact.
    2. Stray quotes: escaped as "" so the value is preserved.

    The first pass only inspects. The file is rewritten (to a temp copy) only if
    something needs fixing. Returns the path to parse and counts for the metadata."""
    stats = {"non_utf8_lines": 0, "repaired_quote_lines": 0}
    with open(path, "rb") as f:
        for raw in f:
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                stats["non_utf8_lines"] += 1
                line = raw.decode("cp1252", errors="replace")
            if STRAY_QUOTE.search(line):
                stats["repaired_quote_lines"] += 1
    if not any(stats.values()):
        return path, stats

    fd, tmp_name = tempfile.mkstemp(suffix=".clean.csv")
    tmp = Path(tmp_name)
    with open(path, "rb") as src, open(fd, "w", encoding="utf-8", newline="") as dst:
        for raw in src:
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                line = raw.decode("cp1252", errors="replace")
            dst.write(STRAY_QUOTE.sub('""', line))
    return tmp, stats


def norm_col(name: str) -> str:
    """'code | 1 | type' -> 'code|1|type'. Keyword parts are lower-cased;
    payer and plan names inside wide columns keep their case."""
    parts = [p.strip() for p in (name or "").strip().lstrip("﻿").split("|")]
    keywords = {"standard_charge", "median_amount", "10th_percentile", "90th_percentile",
                "count", "estimated_amount", "additional_payer_notes", "code"}
    if parts and parts[0].lower() in keywords and len(parts) >= 3 and parts[0].lower() != "code":
        # wide payer column: keep payer/plan as-is, lower the field name
        parts[0] = parts[0].lower()
        if len(parts) >= 4:
            parts[-1] = parts[-1].lower()
        return "|".join(parts)
    return "|".join(p.lower() for p in parts)


def read_header(path: Path) -> tuple[dict, list[str], int]:
    """Returns (metadata, normalized column names, number of physical lines before data).
    Standard files have 2 metadata rows then the column header row; some older or
    non-compliant files start straight with the column header."""
    lines_seen = 0

    def counting_lines(f):
        nonlocal lines_seen
        for line in f:
            lines_seen += 1
            yield line

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(counting_lines(f))
        records = []
        for rec in reader:
            records.append(rec)
            normalized = [norm_col(c) for c in rec]
            if "description" in normalized:
                meta = metadata_from_rows(records[0], records[1]) if len(records) == 3 else {}
                return meta, normalized, lines_seen
            if len(records) >= 3:
                break
    raise ParseError("Could not find a header row containing 'description' in the first 3 rows")


def metadata_from_rows(keys: list[str], values: list[str]) -> dict:
    meta = {}
    for k, v in zip(keys, values):
        k, v = (k or "").strip(), (v or "").strip()
        if not k:
            continue
        kl = k.lower()
        if kl.startswith("license_number"):
            meta["license_number"] = v
            meta["license_state"] = k.split("|")[1].strip().upper() if "|" in k else None
        elif kl.startswith("to the best of its knowledge"):
            meta["attestation_confirmed"] = v.upper() == "TRUE"
        elif kl in ("location_name", "hospital_location", "hospital_address", "type_2_npi"):
            key = "location_name" if kl == "hospital_location" else kl
            meta[key] = [p.strip() for p in v.split("|") if p.strip()]
        else:
            meta[kl] = v
    return meta


def parse_csv(path: Path, out_file: Path) -> tuple[dict, int, str]:
    path, cleaning = prepare_csv(path)
    meta, cols, skip = read_header(path)
    meta.update(cleaning)
    idx = {c: i for i, c in enumerate(cols) if c}

    is_tall = "payer_name" in idx
    wide_groups = wide_payer_columns(cols)
    if not is_tall and not wide_groups and "standard_charge|gross" not in idx:
        raise ParseError("Neither tall (payer_name column) nor wide (payer columns) layout detected")
    fmt = "csv_tall" if is_tall else "csv_wide"

    col_defs = ", ".join(f"'c{i}': 'VARCHAR'" for i in range(len(cols)))
    con = duckdb.connect(str(Path(tempfile.mkdtemp()) / "parse.duckdb"))  # on disk so big files can spill
    con.execute(f"""
        create table raw as
        select * from read_csv('{path}', skip={skip}, header=false, columns={{{col_defs}}},
                               null_padding=true, quote='"', escape='"', parallel=false)
    """)

    def ref(name):  # column reference or NULL if the file doesn't have it
        return f"c{idx[name]}" if name in idx else "NULL"

    base = {out: ref(src) for src, out in BASE_COLUMNS.items()}
    base["codes"] = codes_expr(cols)

    if is_tall:
        payer = {out: ref(src) for src, out in TALL_PAYER_COLUMNS.items()}
        selects = [select_sql({**base, **payer})]
    else:
        selects = [select_sql(base)]  # one gross/cash row per item
        for (payer_name, plan_name), fields in wide_groups.items():
            payer = {out: f"c{i}" for out, i in fields.items()}
            payer["payer_name"] = sql_str(payer_name)
            payer["plan_name"] = sql_str(plan_name)
            any_value = " or ".join(f"nullif(trim(c{i}), '') is not null" for i in fields.values())
            selects.append(select_sql({**base, **payer}, where=any_value))

    rows = 0
    con.execute(f"copy ({' union all '.join(selects)}) to '{out_file}' (format parquet, compression zstd)")
    rows = con.execute(f"select count(*) from '{out_file}'").fetchone()[0]
    con.close()
    return meta, rows, fmt


def wide_payer_columns(cols: list[str]) -> dict[tuple[str, str], dict[str, int]]:
    groups: dict[tuple[str, str], dict[str, int]] = {}
    for i, c in enumerate(cols):
        parts = c.split("|")
        if len(parts) < 3:
            continue
        prefix = parts[0]
        field = parts[3] if len(parts) >= 4 else None
        out = WIDE_PREFIX_FIELDS.get((prefix, field))
        if out:
            groups.setdefault((parts[1], parts[2]), {})[out] = i
    return groups


def codes_expr(cols: list[str]) -> str:
    """Collect code|1, code|1|type, code|2, ... into a list of {code, type} structs."""
    pairs = []
    for i, c in enumerate(cols):
        m = re.fullmatch(r"code\|(\d+)", c)
        if m and f"code|{m.group(1)}|type" in cols:
            t = cols.index(f"code|{m.group(1)}|type")
            pairs.append(f"struct_pack(code := trim(c{i}), type := upper(trim(c{t})))")
    if not pairs:
        return "[]"
    return f"list_filter([{', '.join(pairs)}], x -> coalesce(x.code, '') <> '')"


def select_sql(values: dict[str, str], where: str | None = None) -> str:
    parts = []
    for field in SCHEMA:
        expr = values.get(field.name, "NULL")
        if field.name in NUMERIC and expr != "NULL":
            expr = f"try_cast(nullif(regexp_replace(trim({expr}), '[$,]', '', 'g'), '') as double)"
        elif field.type == pa.string() and expr.startswith("c"):
            expr = f"nullif(trim({expr}), '')"
        parts.append(f"cast({expr} as {DUCK_TYPES[field.type]}) as {field.name}")
    sql = "select " + ", ".join(parts) + " from raw"
    return sql + (f" where {where}" if where else "")


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# ----------------------------------------------------------------------------
# JSON (streamed)
# ----------------------------------------------------------------------------
BIG_KEYS = {"standard_charge_information", "modifier_information"}


def parse_json(path: Path, out_file: Path, batch_size: int = 50_000) -> tuple[dict, int]:
    meta = json_metadata(path)
    writer = pq.ParquetWriter(out_file, SCHEMA, compression="zstd")
    batch, rows = [], 0
    with open(path, "rb") as f:
        for item in ijson.items(f, "standard_charge_information.item"):
            for row in json_item_rows(item):
                batch.append(row)
                if len(batch) >= batch_size:
                    writer.write_table(pa.Table.from_pylist(batch, SCHEMA))
                    rows += len(batch)
                    batch = []
    if batch:
        writer.write_table(pa.Table.from_pylist(batch, SCHEMA))
        rows += len(batch)
    writer.close()
    return meta, rows


def json_metadata(path: Path) -> dict:
    """Build every top-level key EXCEPT the huge arrays, without loading them."""
    builder = ijson.ObjectBuilder()
    skipping = None
    with open(path, "rb") as f:
        for prefix, event, value in ijson.parse(f):
            if skipping:
                if prefix == skipping and event in ("end_array", "end_map"):
                    skipping = None
                continue
            if prefix == "" and event == "map_key" and value in BIG_KEYS:
                skipping = value
                continue
            builder.event(event, value)
    raw = builder.value or {}
    lic = raw.get("license_information") or {}
    att = raw.get("attestation") or raw.get("affirmation") or {}
    return {
        "hospital_name": raw.get("hospital_name"),
        "last_updated_on": raw.get("last_updated_on"),
        "version": raw.get("version"),
        "location_name": raw.get("location_name") or raw.get("hospital_location"),
        "hospital_address": raw.get("hospital_address"),
        "type_2_npi": raw.get("type_2_npi"),
        "license_number": lic.get("license_number"),
        "license_state": lic.get("state"),
        "attestation_confirmed": att.get("confirm_attestation", att.get("confirm_affirmation")),
        "attester_name": att.get("attester_name"),
    }


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def json_item_rows(item: dict):
    codes = [{"code": str(c.get("code", "")).strip(), "type": str(c.get("type", "")).upper().strip()}
             for c in item.get("code_information", []) if c.get("code")]
    drug = item.get("drug_information") or {}
    for sc in item.get("standard_charges", []):
        base = {
            "description": item.get("description"),
            "codes": codes,
            "setting": sc.get("setting"),
            "modifiers": "|".join(sc.get("modifier_code", []) or []) or None,
            "drug_unit": str(drug["unit"]) if drug.get("unit") is not None else None,
            "drug_unit_type": drug.get("type"),
            "gross_charge": num(sc.get("gross_charge")),
            "discounted_cash": num(sc.get("discounted_cash")),
            "min_charge": num(sc.get("minimum")),
            "max_charge": num(sc.get("maximum")),
            "notes": sc.get("additional_generic_notes"),
        }
        yield base  # gross/cash row, same convention as wide CSV
        for p in sc.get("payers_information", []) or []:
            yield {
                **base,
                "payer_name": p.get("payer_name"),
                "plan_name": p.get("plan_name"),
                "negotiated_dollar": num(p.get("standard_charge_dollar")),
                "negotiated_percentage": num(p.get("standard_charge_percentage")),
                "negotiated_algorithm": p.get("standard_charge_algorithm"),
                "methodology": p.get("methodology"),
                "median_amount": num(p.get("median_amount")),
                "p10_amount": num(p.get("10th_percentile")),
                "p90_amount": num(p.get("90th_percentile")),
                "allowed_count": str(p["count"]) if p.get("count") is not None else None,
                "estimated_amount": num(p.get("estimated_amount")),
                "notes": p.get("additional_payer_notes") or base["notes"],
            }
