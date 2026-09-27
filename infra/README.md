# AWS setup

This folder defines every AWS resource the pipeline uses, as code (Terraform):

| File | What it creates |
|---|---|
| `s3.tf` | One private bucket: encrypted, HTTPS-only, versioned, with lifecycle rules that delete old query results and old file versions |
| `glue.tf` | Two Glue databases and the two tables Athena reads (`charges` Parquet, partitioned by hospital, and `hospitals` JSON) |
| `athena.tf` | An Athena workgroup that cancels any query scanning more than 2 GiB (cost guardrail) |
| `budget.tf` | A $5/month budget that emails you at 80% of actual spend and 100% of forecast |
| `github_oidc.tf` | A role GitHub Actions can assume **without stored AWS keys**, limited to this bucket, workgroup and these Glue databases, from this repo's `main` branch only |

## What it costs

At this data size (three hospitals, a few hundred MB of Parquet), a full weekly run costs **a few cents a month**:

- **S3:** about $0.023 per GB-month. Raw files plus Parquet are about 1 GB, so roughly $0.02.
- **Athena:** $5 per TB scanned, with a 10 MB minimum per query. A full `dbt build` scans a few GB at most, about $0.01–0.02 per run.
- **Glue Data Catalog:** free for the first million objects.

The budget alert is there in case something goes wrong, like a loop re-running queries.

## One-time setup (about 30 minutes)

### 1. AWS account and your own credentials

1. Create an AWS account at aws.amazon.com and **turn on MFA for the root user** (IAM → Security credentials).
2. Don't use the root user day to day. In IAM, create a user for yourself (e.g. `ahmed-admin`), attach `AdministratorAccess`, turn on MFA, and create an **access key** for "Command Line Interface".
3. Install the AWS CLI into the project's virtualenv (no admin rights needed) and save the key under a named profile:
   ```bash
   source .venv/bin/activate
   pip install awscli
   aws configure --profile hospital-prices   # paste the key, region us-east-1, output json
   export AWS_PROFILE=hospital-prices
   aws sts get-caller-identity               # should print your account ID
   ```

### 2. Install Terraform (no admin rights needed)

Download the macOS ARM64 zip from the Terraform downloads page (developer.hashicorp.com/terraform/install), then:
```bash
mkdir -p ~/bin && unzip ~/Downloads/terraform_*_darwin_arm64.zip -d ~/bin
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
terraform -version
```
(If you have Homebrew: `brew tap hashicorp/tap && brew install hashicorp/tap/terraform`.)

### 3. Create the infrastructure

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # then put your email in it
terraform init
terraform plan      # read what it will create: 1 bucket (+ settings), 2 Glue DBs, 2 tables, 1 workgroup, 1 budget, OIDC role
terraform apply
terraform output -raw shell_exports             # copy these three export lines
cd ..
```
Commit the generated `infra/.terraform.lock.hcl` (it pins the provider version). Never commit `terraform.tfvars` or `*.tfstate`; `.gitignore` already excludes them.

### 4. First run from your Mac

```bash
pip install -r requirements-aws.txt
# paste the three export lines from `terraform output -raw shell_exports`, plus:
export AWS_PROFILE=hospital-prices

python -m ingest publish                                      # upload parsed files, register partitions
cd transform && dbt build --profiles-dir . --target athena --full-refresh && cd ..
python dashboard/build.py --source athena                     # dashboard from the Athena marts
```

### 5. Let GitHub Actions run it weekly

In the GitHub repo: **Settings → Secrets and variables → Actions → Variables → New repository variable**, and add:

| Name | Value |
|---|---|
| `AWS_ROLE_ARN` | `terraform output -raw github_role_arn` |
| `AWS_REGION` | `us-east-1` |
| `HPT_BUCKET` | `terraform output -raw bucket` |
| `ATHENA_WORKGROUP` | `terraform output -raw athena_workgroup` |

These are variables, not secrets. None of them grants access by itself; only a workflow on this repo's `main` branch can assume the role. Then go to **Actions → AWS pipeline → Run workflow**. After that it runs every Monday.

## Tearing it down

```bash
cd infra && terraform destroy
```
This deletes everything, including the bucket and its contents. That's safe, because every file in it is public data the pipeline can re-download.
