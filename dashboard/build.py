"""
Build the dashboard: export the dbt marts to JSON and bake them into one static
HTML page (dashboard/site/index.html). No server, no BI license, no trial to
expire -- GitHub Pages hosts it for free.

Usage:
  python dashboard/build.py                   # read the local DuckDB warehouse
  python dashboard/build.py --source athena   # read the AWS marts (needs HPT_BUCKET, AWS_REGION, ATHENA_WORKGROUP)
"""
import argparse
import json
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = Path(os.environ.get("WAREHOUSE", ROOT / "data" / "warehouse.duckdb"))
TEMPLATE = Path(__file__).with_name("template.html")
OUT = Path(__file__).with_name("site") / "index.html"
ATHENA_SCHEMA = "hospital_prices"  # Glue database dbt builds into (see transform/profiles.yml)


def connect(source):
    """Both drivers follow the Python DB-API, so the queries below run unchanged on either."""
    if source == "athena":
        from pyathena import connect as athena_connect
        conn = athena_connect(
            region_name=os.environ["AWS_REGION"],
            work_group=os.environ["ATHENA_WORKGROUP"],
            s3_staging_dir=f"s3://{os.environ['HPT_BUCKET']}/athena-results/",
        )
        return conn, f"{ATHENA_SCHEMA}."
    import duckdb
    return duckdb.connect(str(WAREHOUSE), read_only=True), ""


def rows(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["duckdb", "athena"], default="duckdb")
    args = parser.parse_args()

    conn, s = connect(args.source)
    data = {
        "prices": rows(conn, f"""
            select category, service_name, billing_code, hospital_name, payer_group, product_line,
                   plan_rates, min_rate, median_rate, max_rate, median_actually_paid,
                   gross_charge, cash_price, includes_percentage_rates, pct_of_medicare
            from {s}mart_service_prices
            order by category, service_name, hospital_name, payer_group"""),
        "dispersion": rows(conn, f"select * from {s}mart_price_dispersion order by high_to_low_ratio desc"),
        "hospitals": rows(conn, f"""
            select hospital_name, cast(last_updated_on as varchar) as last_updated_on,
                   schema_version, source_format
            from {s}dim_hospital order by hospital_name"""),
        "built_on": date.today().isoformat(),
        "source": args.source,
    }
    data["is_demo"] = any("FICTIONAL" in h["hospital_name"] for h in data["hospitals"])
    conn.close()

    # </ can't appear inside a <script> block; Decimal values become floats
    payload = json.dumps(data, default=float).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(data['prices'])} price rows, "
          f"{len(data['hospitals'])} hospitals, {OUT.stat().st_size / 1024:.0f} KB, from {args.source})")


if __name__ == "__main__":
    main()
