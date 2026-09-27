# Two Glue databases (Athena calls them schemas):
#   hospital_prices_raw  -- tables over the files the ingest step uploads
#   hospital_prices      -- where dbt builds its models

resource "aws_glue_catalog_database" "raw" {
  name        = "hospital_prices_raw"
  description = "Parsed hospital price files uploaded by the ingest step."
}

resource "aws_glue_catalog_database" "models" {
  name        = "hospital_prices"
  description = "dbt models built by Athena."
}

locals {
  curated = "s3://${aws_s3_bucket.data.bucket}/curated"

  # Must match ingest/parse.py SCHEMA exactly (tests/test_parse.py checks this).
  charges_columns = [
    { name = "description", type = "string" },
    { name = "codes", type = "array<struct<code:string,type:string>>" },
    { name = "setting", type = "string" },
    { name = "modifiers", type = "string" },
    { name = "drug_unit", type = "string" },
    { name = "drug_unit_type", type = "string" },
    { name = "gross_charge", type = "double" },
    { name = "discounted_cash", type = "double" },
    { name = "min_charge", type = "double" },
    { name = "max_charge", type = "double" },
    { name = "payer_name", type = "string" },
    { name = "plan_name", type = "string" },
    { name = "negotiated_dollar", type = "double" },
    { name = "negotiated_percentage", type = "double" },
    { name = "negotiated_algorithm", type = "string" },
    { name = "methodology", type = "string" },
    { name = "median_amount", type = "double" },
    { name = "p10_amount", type = "double" },
    { name = "p90_amount", type = "double" },
    { name = "allowed_count", type = "string" },
    { name = "estimated_amount", type = "double" },
    { name = "notes", type = "string" },
  ]

  hospitals_columns = [
    { name = "hospital_id", type = "string" },
    { name = "hospital_name", type = "string" },
    { name = "last_updated_on", type = "string" },
    { name = "version", type = "string" },
    { name = "location_name", type = "array<string>" },
    { name = "hospital_address", type = "array<string>" },
    { name = "type_2_npi", type = "array<string>" },
    { name = "license_number", type = "string" },
    { name = "license_state", type = "string" },
    { name = "attestation_confirmed", type = "boolean" },
    { name = "attester_name", type = "string" },
    { name = "source_file", type = "string" },
    { name = "source_format", type = "string" },
    { name = "row_count", type = "bigint" },
    { name = "parsed_at", type = "string" },
    { name = "repaired_quote_lines", type = "bigint" },
    { name = "non_utf8_lines", type = "bigint" },
  ]
}

# One row per item x setting x payer x plan, partitioned by hospital.
# The ingest step registers each hospital's partition after uploading it.
resource "aws_glue_catalog_table" "charges" {
  name          = "charges"
  database_name = aws_glue_catalog_database.raw.name
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL              = "TRUE"
    classification        = "parquet"
    "parquet.compression" = "ZSTD"
  }

  partition_keys {
    name = "hospital_id"
    type = "string"
  }

  storage_descriptor {
    location      = "${local.curated}/charges/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.charges_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

# One JSON object per line, one file per hospital.
resource "aws_glue_catalog_table" "hospitals" {
  name          = "hospitals"
  database_name = aws_glue_catalog_database.raw.name
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL       = "TRUE"
    classification = "json"
  }

  storage_descriptor {
    location      = "${local.curated}/hospitals/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        "ignore.malformed.json" = "false" # fail loudly rather than silently drop a hospital
      }
    }

    dynamic "columns" {
      for_each = local.hospitals_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
