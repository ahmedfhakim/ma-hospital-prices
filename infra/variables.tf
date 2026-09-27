variable "aws_region" {
  description = "AWS region for every resource."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for resources."
  type        = string
  default     = "hospital-prices"
}

variable "github_repo" {
  description = "GitHub repository (owner/name) allowed to run the pipeline through OIDC."
  type        = string
  default     = "ahmedfhakim/ma-hospital-prices"
}

variable "budget_email" {
  description = "Where AWS Budgets sends cost alerts."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget. Alerts at 80% of actual spend and 100% of forecast."
  type        = number
  default     = 5
}

variable "athena_bytes_scanned_cutoff" {
  description = "Athena cancels any single query that would scan more than this many bytes (cost guardrail)."
  type        = number
  default     = 2147483648 # 2 GiB. A full dbt build scans well under this per query.
}

variable "create_github_oidc_provider" {
  description = "An AWS account can hold only one GitHub OIDC provider. Set false if yours already has one."
  type        = bool
  default     = true
}
