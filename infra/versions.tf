terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State is kept locally (infra/terraform.tfstate, git-ignored). It holds resource IDs,
  # not secrets. For a team you'd move it to an S3 backend with locking.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Repo      = var.github_repo
    }
  }
}

data "aws_caller_identity" "current" {}
