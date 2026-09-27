# One private bucket for the whole pipeline:
#   raw/<hospital_id>/<file>                        original price files, as downloaded
#   curated/charges/hospital_id=<id>/data.parquet   parsed, standard layout (Glue table: charges)
#   curated/hospitals/<id>.json                     file metadata + lineage (Glue table: hospitals)
#   warehouse/<schema>/<table>/                     tables dbt builds in Athena
#   athena-results/                                 query results (auto-deleted after 7 days)

resource "aws_s3_bucket" "data" {
  # account ID suffix keeps the (globally unique) name from colliding with anyone else's
  bucket = "${var.project}-${data.aws_caller_identity.current.account_id}"

  # Everything in here is public data that the pipeline can re-download, so let
  # `terraform destroy` delete the bucket even when it isn't empty.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced" # ACLs disabled; access is IAM-only
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning keeps the previous copy of a price file when a hospital republishes it --
# the raw material for tracking price changes over time.
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket     = aws_s3_bucket.data.id
  depends_on = [aws_s3_bucket_versioning.data]

  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter {
      prefix = "athena-results/"
    }
    expiration {
      days = 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "limit-old-versions"
    status = "Enabled"
    filter {} # whole bucket
    noncurrent_version_expiration {
      noncurrent_days           = 90
      newer_noncurrent_versions = 3 # always keep the 3 most recent old versions
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }
  }
}

# Refuse any request that isn't over HTTPS.
data "aws_iam_policy_document" "tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket     = aws_s3_bucket.data.id
  policy     = data.aws_iam_policy_document.tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.data]
}
