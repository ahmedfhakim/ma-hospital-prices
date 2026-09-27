resource "aws_athena_workgroup" "main" {
  name          = var.project
  force_destroy = true # lets `terraform destroy` remove it even if it has saved query history

  configuration {
    enforce_workgroup_configuration    = true # clients can't override these settings
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
