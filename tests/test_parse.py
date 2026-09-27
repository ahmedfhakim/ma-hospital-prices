"""
Parser tests against CMS's own example files (tests/fixtures, from
github.com/CMSgov/hospital-price-transparency).

The strongest check: CMS publishes the SAME example hospital in tall CSV,
wide CSV and JSON. Parsed, all three must produce the same payer-level rates.

Run:  pytest -q
"""
from pathlib import Path

import duckdb
import pytest

from ingest.discover import parse_index
from ingest.parse import parse_file

FIX = Path(__file__).parent / "fixtures"
RATE_COLS = ("description, setting, payer_name, plan_name, negotiated_dollar, negotiated_percentage, "
             "negotiated_algorithm, median_amount, p10_amount, p90_amount, allowed_count, methodology")


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    out = tmp_path_factory.mktemp("parquet")
    metas = {f.stem: parse_file(f, f.stem, out) for f in sorted(FIX.iterdir()) if f.suffix in (".csv", ".json")}
    return out, metas


def rates(out, hid, extra_where=""):
    return f"""select {RATE_COLS} from read_parquet('{out}/charges/hospital_id={hid}/*.parquet')
               where payer_name is not null {extra_where}"""


def test_every_fixture_parses(parsed):
    _, metas = parsed
    assert {m["source_format"] for m in metas.values()} == {"csv_tall", "csv_wide", "json"}
    assert all(m["row_count"] > 0 for m in metas.values())


def test_v3_tall_and_wide_are_identical(parsed):
    out, _ = parsed
    a, b = rates(out, "cms_example_v3_tall"), rates(out, "cms_example_v3_wide")
    assert duckdb.sql(f"select count(*) from (({a}) except all ({b}))").fetchone()[0] == 0
    assert duckdb.sql(f"select count(*) from (({b}) except all ({a}))").fetchone()[0] == 0


def test_v3_json_matches_csv_except_modifier_rows(parsed):
    # JSON keeps modifier adjustments in a separate section that the parser skips on purpose,
    # so compare everything except the CSV rows that describe modifiers.
    out, _ = parsed
    j = rates(out, "cms_example_v3")
    t = rates(out, "cms_example_v3_tall", "and codes = []")  # modifier rows carry no billing code
    t_coded = rates(out, "cms_example_v3_tall", "and codes <> []")
    assert duckdb.sql(f"select count(*) from (({t_coded}) except all ({j}))").fetchone()[0] == 0
    assert duckdb.sql(f"select count(*) from (({j}) except all ({t_coded}))").fetchone()[0] == 0
    assert duckdb.sql(f"select count(*) from ({t})").fetchone()[0] > 0


def test_windows_1252_file_is_transcoded(parsed):
    _, metas = parsed
    assert metas["cms_example_v2_wide"]["row_count"] > 0  # this CMS example is not valid UTF-8


def test_metadata(parsed):
    _, metas = parsed
    m = metas["cms_example_v3_tall"]
    assert m["hospital_name"] == "West Mercy Hospital"
    assert m["version"] == "3.0.0"
    assert m["license_state"] == "CA"
    assert m["type_2_npi"] == ["0000000001", "0000000002", "0000000003"]
    assert metas["cms_example_v3"]["type_2_npi"] == m["type_2_npi"]


def test_cms_hpt_index_parsing():
    text = """location-name: Hospital A
source-page-url: https://a.org/prices
mrf-url: https://a.org/a.csv
contact-name: X
contact-email: x@a.org
location-name: Hospital B
mrf-url: https://a.org/b.json
"""
    entries = parse_index(text)
    assert [e["location-name"] for e in entries] == ["Hospital A", "Hospital B"]
    assert entries[1]["mrf-url"] == "https://a.org/b.json"


def test_stray_quote_is_repaired_not_dropped(tmp_path):
    # Real-world case (Boston Medical Center, 2026): an inch mark inside a quoted field.
    src = (FIX / "cms_example_v3_tall.csv").read_text(encoding="utf-8-sig")
    src = src.replace('"MRI of brain (no contrast)"', '"VAGINAL DILATOR SZ4 ORNG 9"X 1"', 1)
    if '9"X 1' not in src:  # description may be unquoted in the example file
        src = src.replace("MRI of brain (no contrast)", '"VAGINAL DILATOR SZ4 ORNG 9"X 1"', 1)
    bad = tmp_path / "stray_quote.csv"
    bad.write_text(src, encoding="utf-8")

    meta = parse_file(bad, "stray", tmp_path / "out")
    assert meta["repaired_quote_lines"] == 1
    got = duckdb.sql(f"""select count(*) from read_parquet('{tmp_path}/out/charges/hospital_id=stray/*.parquet')
                         where description = 'VAGINAL DILATOR SZ4 ORNG 9"X 1'""").fetchone()[0]
    assert got == 1
    assert meta["row_count"] == 45  # nothing lost


def test_legacy_tls_is_opt_in_and_still_verifies_certificates():
    import ssl
    from ingest.http import LegacyRenegotiationAdapter, OP_LEGACY_SERVER_CONNECT, make_session

    strict = make_session()
    assert not isinstance(strict.get_adapter("https://example.org"), LegacyRenegotiationAdapter)

    legacy = make_session(legacy_tls=True)
    adapter = legacy.get_adapter("https://example.org")
    assert isinstance(adapter, LegacyRenegotiationAdapter)
    ctx = adapter._context()
    assert ctx.options & OP_LEGACY_SERVER_CONNECT          # old handshake allowed...
    assert ctx.verify_mode == ssl.CERT_REQUIRED             # ...but certificates still checked
    assert ctx.check_hostname
