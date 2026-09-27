"""
Publishing to S3 + Athena, tested against moto's in-memory fake AWS (no account needed).
"""
import json
import shutil

import boto3
import pytest

moto = pytest.importorskip("moto")

from ingest.cloud import publish  # noqa: E402
from ingest.download import sha256_of  # noqa: E402
from ingest.parse import parse_file  # noqa: E402

from .test_parse import FIX  # noqa: E402

BUCKET = "hospital-prices-test"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("HPT_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ATHENA_WORKGROUP", "hospital-prices")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        athena = boto3.client("athena", region_name="us-east-1")
        athena.create_work_group(Name="hospital-prices")
        yield s3, athena


def test_publish_uploads_then_skips_unchanged(tmp_path, aws, capsys):
    s3, athena = aws
    data = tmp_path / "data"
    raw = data / "landing" / "west_mercy" / "west_mercy.csv"
    raw.parent.mkdir(parents=True)
    shutil.copy(FIX / "cms_example_v3_tall.csv", raw)
    parse_file(raw, "west_mercy", data / "parquet")
    manifest = {"west_mercy": {"path": str(raw), "sha256": sha256_of(raw)}}

    publish(data, manifest, s3=s3, athena=athena)
    keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"])
    assert keys == [
        "curated/charges/hospital_id=west_mercy/data.parquet",
        "curated/hospitals/west_mercy.json",
        "raw/west_mercy/west_mercy.csv",
    ]
    assert "raw, charges, metadata" in capsys.readouterr().out

    # Athena's JSON reader needs exactly one object per line
    body = s3.get_object(Bucket=BUCKET, Key="curated/hospitals/west_mercy.json")["Body"].read().decode()
    assert body.count("\n") == 1
    assert json.loads(body)["type_2_npi"] == ["0000000001", "0000000002", "0000000003"]

    # the partition was registered
    queries = athena.list_query_executions(WorkGroup="hospital-prices")["QueryExecutionIds"]
    sql = athena.get_query_execution(QueryExecutionId=queries[0])["QueryExecution"]["Query"]
    assert "ADD IF NOT EXISTS PARTITION (hospital_id = 'west_mercy')" in sql

    # second run: nothing changed, nothing uploaded
    publish(data, manifest, s3=s3, athena=athena)
    assert "no changes" in capsys.readouterr().out


def test_publish_requires_configuration(monkeypatch, tmp_path):
    for var in ("HPT_BUCKET", "AWS_REGION", "ATHENA_WORKGROUP"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit, match="terraform"):
        publish(tmp_path, {})
