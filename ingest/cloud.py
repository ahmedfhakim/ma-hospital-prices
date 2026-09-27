"""
Publish parsed hospital files to S3 and register them with Athena.

    python -m ingest publish              # every parsed hospital
    python -m ingest publish --only bmc   # one hospital
    python -m ingest publish --skip-raw   # parsed files only (raw files can be ~500 MB each)

S3 layout (the bucket and Glue tables come from infra/, via Terraform):
    raw/<hospital_id>/<original file>                  as downloaded
    curated/charges/hospital_id=<id>/data.parquet      Glue table hospital_prices_raw.charges
    curated/hospitals/<id>.json                        Glue table hospital_prices_raw.hospitals

Uploads are skipped when S3 already holds identical content (SHA-256 stored in the
object's metadata), so re-running is cheap and doesn't pile up S3 versions.

Configuration comes from environment variables (printed by `terraform output shell_exports`):
    HPT_BUCKET, AWS_REGION, ATHENA_WORKGROUP, and optionally ATHENA_RAW_DATABASE.
AWS credentials come from the normal AWS chain: your profile locally, OIDC in GitHub Actions.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import boto3

from .download import sha256_of

LIST_FIELDS = ("location_name", "hospital_address", "type_2_npi")


def config() -> dict:
    missing = [k for k in ("HPT_BUCKET", "AWS_REGION", "ATHENA_WORKGROUP") if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"Missing environment variable(s): {', '.join(missing)}.\n"
            "Run `terraform -chdir=infra output -raw shell_exports` and paste the result."
        )
    return {
        "bucket": os.environ["HPT_BUCKET"],
        "region": os.environ["AWS_REGION"],
        "workgroup": os.environ["ATHENA_WORKGROUP"],
        "raw_database": os.environ.get("ATHENA_RAW_DATABASE", "hospital_prices_raw"),
    }


def upload_if_changed(s3, local: Path, bucket: str, key: str, sha: str | None = None) -> bool:
    """Upload unless S3 already has identical content. Returns True if uploaded."""
    sha = sha or sha256_of(local)
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
        if head.get("Metadata", {}).get("sha256") == sha:
            return False
    except s3.exceptions.ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise
    s3.upload_file(str(local), bucket, key, ExtraArgs={"Metadata": {"sha256": sha}})
    return True


def hospital_json_line(meta_path: Path) -> str:
    """Athena's JSON reader needs one object per line, with consistent types."""
    meta = json.loads(meta_path.read_text())
    for field in LIST_FIELDS:  # some files give a single string where the schema has a list
        value = meta.get(field)
        if isinstance(value, str):
            meta[field] = [value]
    return json.dumps(meta, default=str) + "\n"


def run_athena(athena, sql: str, workgroup: str, timeout_s: int = 120) -> None:
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup)["QueryExecutionId"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if state["State"] == "SUCCEEDED":
            return
        if state["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Athena query failed: {state.get('StateChangeReason')}\n{sql}")
        time.sleep(1)
    raise TimeoutError(f"Athena query still running after {timeout_s}s: {sql}")


def publish(data_dir: Path, manifest: dict, only: str | None = None, skip_raw: bool = False,
            s3=None, athena=None) -> list[str]:
    cfg = config()
    s3 = s3 or boto3.client("s3", region_name=cfg["region"])
    athena = athena or boto3.client("athena", region_name=cfg["region"])
    bucket = cfg["bucket"]
    parquet_dir = data_dir / "parquet"

    hospital_ids = sorted(p.stem for p in (parquet_dir / "hospitals").glob("*.json"))
    if only:
        hospital_ids = [h for h in hospital_ids if h == only]
    if not hospital_ids:
        raise SystemExit(f"No parsed hospitals found in {parquet_dir}. Run `python -m ingest run` first.")

    published = []
    for hid in hospital_ids:
        t0 = time.time()
        changed = []

        # 1. raw file, as downloaded (kept for lineage and re-parsing)
        raw_path = manifest.get(hid, {}).get("path")
        if not skip_raw and raw_path and Path(raw_path).exists():
            key = f"raw/{hid}/{Path(raw_path).name}"
            if upload_if_changed(s3, Path(raw_path), bucket, key, manifest[hid].get("sha256")):
                changed.append("raw")

        # 2. parsed charges (Parquet)
        parquet = parquet_dir / "charges" / f"hospital_id={hid}" / "data.parquet"
        prefix = f"curated/charges/hospital_id={hid}/"
        if upload_if_changed(s3, parquet, bucket, prefix + "data.parquet"):
            changed.append("charges")

        # 3. hospital metadata (one JSON line)
        line_file = parquet_dir / "hospitals" / f".{hid}.jsonl"
        line_file.write_text(hospital_json_line(parquet_dir / "hospitals" / f"{hid}.json"))
        if upload_if_changed(s3, line_file, bucket, f"curated/hospitals/{hid}.json"):
            changed.append("metadata")
        line_file.unlink()

        # 4. tell Athena the partition exists (no-op if it already does)
        hid_sql = hid.replace("'", "''")
        run_athena(athena, (
            f"ALTER TABLE {cfg['raw_database']}.charges ADD IF NOT EXISTS "
            f"PARTITION (hospital_id = '{hid_sql}') LOCATION 's3://{bucket}/{prefix}'"
        ), cfg["workgroup"])

        print(f"[{hid}] published: {', '.join(changed) or 'no changes'} ({time.time() - t0:.1f}s)")
        published.append(hid)
    return published
