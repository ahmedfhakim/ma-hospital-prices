# Lets GitHub Actions run the pipeline WITHOUT stored AWS keys. On each run GitHub
# issues a short-lived signed token; AWS checks it came from this repo's main branch
# and hands back temporary credentials for the role below.

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
  glue_prefix     = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}"
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only workflows running on this repo's main branch (scheduled or manual runs).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name                 = "${var.project}-github-pipeline"
  description          = "Assumed by GitHub Actions (OIDC) to run the hospital prices pipeline."
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# Least privilege: this bucket, this workgroup, these two Glue databases -- nothing else.
data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid = "ReadWriteObjects"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
      "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }

  statement {
    sid = "RunAthenaQueries"
    actions = [
      "athena:StartQueryExecution", "athena:StopQueryExecution",
      "athena:GetQueryExecution", "athena:GetQueryResults",
      "athena:GetQueryRuntimeStatistics", "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.main.arn]
  }

  statement {
    sid       = "AthenaDataCatalog"
    actions   = ["athena:GetDataCatalog", "athena:ListDataCatalogs"]
    resources = ["*"] # these actions don't support resource-level scoping
  }

  statement {
    sid = "GlueCatalog"
    actions = [
      "glue:GetDatabase", "glue:GetDatabases",
      "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable",
      "glue:DeleteTable", "glue:BatchDeleteTable",
      "glue:GetTableVersions", "glue:DeleteTableVersion", "glue:BatchDeleteTableVersion",
      "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition",
      "glue:CreatePartition", "glue:BatchCreatePartition", "glue:UpdatePartition",
      "glue:DeletePartition", "glue:BatchDeletePartition",
    ]
    resources = [
      "${local.glue_prefix}:catalog",
      "${local.glue_prefix}:database/${aws_glue_catalog_database.raw.name}",
      "${local.glue_prefix}:database/${aws_glue_catalog_database.models.name}",
      "${local.glue_prefix}:table/${aws_glue_catalog_database.raw.name}/*",
      "${local.glue_prefix}:table/${aws_glue_catalog_database.models.name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "pipeline-access"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}
