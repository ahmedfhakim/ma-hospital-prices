output "bucket" {
  value = aws_s3_bucket.data.bucket
}

output "athena_workgroup" {
  value = aws_athena_workgroup.main.name
}

output "aws_region" {
  value = var.aws_region
}

output "github_role_arn" {
  description = "Set as the AWS_ROLE_ARN variable in GitHub (Settings -> Secrets and variables -> Actions -> Variables)."
  value       = aws_iam_role.pipeline.arn
}

output "shell_exports" {
  description = "Paste into your terminal to point the ingest, dbt and dashboard commands at AWS."
  value       = <<-EOT
    export AWS_REGION=${var.aws_region}
    export HPT_BUCKET=${aws_s3_bucket.data.bucket}
    export ATHENA_WORKGROUP=${aws_athena_workgroup.main.name}
  EOT
}
