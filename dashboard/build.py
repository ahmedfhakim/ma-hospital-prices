"""
Build the dashboard: export the dbt marts to JSON and bake them into one static
HTML page (dashboard/site/index.html). No server, no BI license, no trial to
expire -- GitHub Pages hosts it for free.

Usage:  python dashboard/build.py
"""
import json
import os
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = Path(os.environ.get("WAREHOUSE", ROOT / "data" / "warehouse.duckdb"))
TEMPLATE = Path(__file__).with_name("template.html")
OUT = Path(__file__).with_name("site") / "index.html"


def rows(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    data = {
        "prices": rows(con, """
            select category, service_name, billing_code, hospital_name, payer_group, product_line,
                   plan_rates, min_rate, median_rate, max_rate, median_actually_paid,
                   gross_charge, cash_price, includes_percentage_rates, pct_of_medicare
            from mart_service_prices
            order by category, service_name, hospital_name, payer_group"""),
        "dispersion": rows(con, "select * from mart_price_dispersion order by high_to_low_ratio desc"),
        "hospitals": rows(con, """
            select hospital_name, last_updated_on::varchar as last_updated_on, schema_version, source_format
            from dim_hospital order by hospital_name"""),
        "built_on": date.today().isoformat(),
    }
    data["is_demo"] = any("FICTIONAL" in h["hospital_name"] for h in data["hospitals"])
    con.close()

    # </ can't appear inside a <script> block
    payload = json.dumps(data, default=float).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(data['prices'])} price rows, "
          f"{len(data['hospitals'])} hospitals, {OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
