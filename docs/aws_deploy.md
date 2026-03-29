# AWS Deploy

This is the exact dev deployment path for `eu-west-2`.

## Prerequisites

- AWS account access for `eu-west-2`
- two private or public subnets for Fargate
- one security group allowing outbound internet access
- GitHub Actions secrets:
  - `AWS_GITHUB_ACTIONS_ROLE_ARN`
  - `AWS_ACCOUNT_ID`

## 1. Local Terraform File

Use [terraform.tfvars.example](/Users/efeon/commitscope/infrastructure/terraform/envs/dev/terraform.tfvars.example) as the local template if you want to run Terraform from your machine. A typical dev file is:

```hcl
project               = "commitscope"
environment           = "dev"
aws_region            = "eu-west-2"
bucket_name           = "commitscope-nick-dev"
athena_database       = "commitscope_dev"
create_ecr_repository = true
ecr_repository_name   = "commitscope-dev"
container_image_uri   = null
subnet_ids            = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
security_group_ids    = ["sg-0123456789abcdef0"]
sample_config_path    = "examples/config.dev.json"
```

This file is not required by the GitHub Actions deployment workflow.

## 2. GitHub Actions Variables And Secrets

Set these GitHub repository secrets:

- `AWS_GITHUB_ACTIONS_ROLE_ARN`
- `AWS_ACCOUNT_ID`

Set these GitHub repository variables:

- `TF_BUCKET_NAME`
- `TF_ATHENA_DATABASE`
- `TF_ECR_REPOSITORY_NAME`
- `TF_SUBNET_IDS_JSON`
- `TF_SECURITY_GROUP_IDS_JSON`
- `TF_STATE_BUCKET`
- `TF_STATE_KEY`

Example variable values:

```text
TF_BUCKET_NAME=commitscope-nick-dev
TF_ATHENA_DATABASE=commitscope_dev
TF_ECR_REPOSITORY_NAME=commitscope-dev
TF_SUBNET_IDS_JSON=["subnet-02686afdabd1e9a42","subnet-0158146133e1d6aa0","subnet-08605bc763c0c8c86"]
TF_SECURITY_GROUP_IDS_JSON=["sg-0c1168281540af705"]
TF_STATE_BUCKET=commitscope-nick-tfstate
TF_STATE_KEY=envs/dev/terraform.tfstate
```

The backend bucket must already exist before `deploy-dev.yml` runs. This repo now uses an S3 remote backend with S3 lockfiles, so GitHub runners no longer rely on ephemeral local `terraform.tfstate`.

## 3. Image Tag Convention

The deploy workflow tags the ECS image with the first 12 characters of the Git commit SHA.

Example:

```text
123456789012.dkr.ecr.eu-west-2.amazonaws.com/commitscope-dev:1a2b3c4d5e6f
```

You can override the tag in the workflow dispatch UI, but the default should remain Git-SHA based.

## 4. Deploy

Trigger [deploy-dev.yml](/Users/efeon/commitscope/.github/workflows/deploy-dev.yml).

What it does:

1. runs `terraform apply` for base infrastructure
2. reads the ECR repository URL from Terraform outputs
3. builds and pushes the container image tagged with the Git SHA
4. runs `terraform apply` again with `container_image_uri=<ecr-url>:<git-sha>`

`terraform init` is performed with `-backend-config=backend.hcl`, generated from the GitHub repo variables above.

## 5. Live Cloud Execution Path

The cloud path is:

1. Step Functions execution starts with the config payload from `commitscope.main dispatch`
2. Lambda prepare step receives `config_json` and turns it into ECS container overrides
3. ECS Fargate task runs `python -m commitscope.aws.container`
4. the pipeline clears the previous `raw/`, `processed/`, and `curated/` objects, then clones the target public GitHub repo, analyses the configured commit range, and writes:
   - `raw/`
   - `processed/`
   - `curated/`
5. the state machine starts the Glue crawler so partitions refresh after a successful run and deleted partitions are removed from Glue
6. Athena queries the Parquet written under `processed/`
7. QuickSight uses Athena-backed direct-query datasets and dashboards provisioned from the repo helper

## 6. Start A Cloud Run

First generate the Step Functions payload:

```bash
PYTHONPATH=src .venv/bin/python -m commitscope.main dispatch --config examples/config.dev.json > stepfunctions-input.json
```

Then start the execution:

```bash
aws stepfunctions start-execution \
  --region eu-west-2 \
  --state-machine-arn "$(terraform -chdir=infrastructure/terraform/envs/dev output -raw state_machine_arn)" \
  --input file://stepfunctions-input.json
```

## 7. Post-Deploy Verification

Confirm Step Functions execution succeeded:

```bash
aws stepfunctions list-executions \
  --region eu-west-2 \
  --state-machine-arn "$(terraform -chdir=infrastructure/terraform/envs/dev output -raw state_machine_arn)" \
  --max-results 5
```

Confirm Lambda ran:

```bash
aws logs tail "/aws/lambda/$(terraform -chdir=infrastructure/terraform/envs/dev output -raw lambda_function_name)" \
  --region eu-west-2 \
  --since 30m
```

Confirm ECS task ran:

```bash
aws ecs list-tasks \
  --region eu-west-2 \
  --cluster "$(terraform -chdir=infrastructure/terraform/envs/dev output -raw ecs_cluster_arn)" \
  --desired-status STOPPED
```

Confirm Parquet landed in S3:

```bash
aws s3 ls "s3://$(terraform -chdir=infrastructure/terraform/envs/dev output -raw data_lake_bucket)/processed/" \
  --recursive | grep '\.parquet$'
```

Confirm Athena tables are queryable:

```bash
aws athena start-query-execution \
  --region eu-west-2 \
  --work-group commitscope-dev-wg \
  --query-string "SELECT count(*) FROM commitscope_dev.commit_summary;" \
  --result-configuration OutputLocation="s3://$(terraform -chdir=infrastructure/terraform/envs/dev output -raw data_lake_bucket)/curated/athena-results/"
```

Confirm QuickSight assets are provisioned and can query Athena:

```bash
.venv/bin/python scripts/provision_quicksight.py
```

Then verify in the QuickSight UI that:

1. the Athena data source exists
2. the datasets preview rows from Athena
3. the `CommitScope Dev Overview` analysis and dashboard load successfully

## Notes

- enable `write_s3` in the config for cloud-backed outputs
- apply the generated DDL from [glue_ddl.sql](/Users/efeon/commitscope/outputs/generated/curated/glue_ddl.sql) if the crawler has not yet registered the tables as expected
- Lambda is intentionally a prepare step only
- ECS Fargate is the heavy-analysis runtime
- QuickSight provisioning is scripted; the generated curated JSON remains useful as an evidence artifact and as a reference asset definition
