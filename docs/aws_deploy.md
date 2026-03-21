# AWS Deploy

This is the exact dev deployment path for `eu-west-2`.

## Prerequisites

- AWS account access for `eu-west-2`
- two private or public subnets for Fargate
- one security group allowing outbound internet access
- GitHub Actions secrets:
  - `AWS_GITHUB_ACTIONS_ROLE_ARN`
  - `AWS_ACCOUNT_ID`

## 1. Create `terraform.tfvars`

Use [terraform.tfvars.example](/Users/efeon/commitscope/infrastructure/terraform/envs/dev/terraform.tfvars.example) as the template. A typical dev file is:

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

## 2. Image Tag Convention

The deploy workflow tags the ECS image with the first 12 characters of the Git commit SHA.

Example:

```text
123456789012.dkr.ecr.eu-west-2.amazonaws.com/commitscope-dev:1a2b3c4d5e6f
```

You can override the tag in the workflow dispatch UI, but the default should remain Git-SHA based.

## 3. Deploy

Trigger [deploy-dev.yml](/Users/efeon/commitscope/.github/workflows/deploy-dev.yml).

What it does:

1. runs `terraform apply` for base infrastructure
2. reads the ECR repository URL from Terraform outputs
3. builds and pushes the container image tagged with the Git SHA
4. runs `terraform apply` again with `container_image_uri=<ecr-url>:<git-sha>`

## 4. Live Cloud Execution Path

The cloud path is:

1. Step Functions execution starts with the config payload from `commitscope.main dispatch`
2. Lambda prepare step receives `config_json` and turns it into ECS container overrides
3. ECS Fargate task runs `python -m commitscope.aws.container`
4. the pipeline clones the target public GitHub repo, analyses the configured commit range, and writes:
   - `raw/`
   - `processed/`
   - `curated/`
5. Athena queries the Parquet written under `processed/`
6. QuickSight uses Athena-backed datasets described in the generated curated artifacts

## 5. Start A Cloud Run

First generate the Step Functions payload:

```bash
PYTHONPATH=src python -m commitscope.main dispatch --config examples/config.dev.json > stepfunctions-input.json
```

Then start the execution:

```bash
aws stepfunctions start-execution \
  --region eu-west-2 \
  --state-machine-arn "$(terraform -chdir=infrastructure/terraform/envs/dev output -raw state_machine_arn)" \
  --input file://stepfunctions-input.json
```

## 6. Post-Deploy Verification

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

Confirm QuickSight can use the generated datasets:

1. open [quicksight_datasets.json](/Users/efeon/commitscope/outputs/generated/curated/quicksight_datasets.json)
2. create Athena datasets in QuickSight for:
   - `commitscope_dev.commit_summary`
   - `commitscope_dev.class_metrics`
   - `commitscope_dev.file_metrics`
3. verify QuickSight can preview rows from each dataset

## Notes

- enable `write_s3` in the config for cloud-backed outputs
- apply the generated DDL from [glue_ddl.sql](/Users/efeon/commitscope/outputs/generated/curated/glue_ddl.sql) if the crawler has not yet registered the tables as expected
- Lambda is intentionally a prepare step only
- ECS Fargate is the heavy-analysis runtime
