# CommitScope

CommitScope is an AWS-first analytics pipeline that turns Git history into queryable code-health datasets. The MVP clones a public GitHub repository, walks a configurable commit range, computes notebook-aligned static-analysis metrics, writes JSON/CSV/Parquet outputs locally and to S3, and prepares Athena-backed datasets for QuickSight.

## MVP Scope

- GitHub URL input for public repositories
- Configurable commit range via branch, `max_commits`, `since`, `until`, `from_commit`, and `to_commit`
- Local outputs in JSON, CSV, and Parquet
- S3 outputs under `raw/`, `processed/`, and `curated/`
- Athena-ready datasets partitioned by `repo`, `branch`, and `commit_date`
- Config-driven execution for local runs or Step Functions -> ECS Fargate
- QuickSight dashboard definition artifacts
- Terraform scaffold for `eu-west-2` dev infrastructure
- ECS Fargate scaffold for heavy analysis jobs
- GitHub Actions CI

## Local Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Run the pipeline with the example config:

```bash
PYTHONPATH=src python -m commitscope.main run --config examples/config.dev.json
```

Generate the Step Functions payload for cloud execution:

```bash
PYTHONPATH=src python -m commitscope.main dispatch --config examples/config.dev.json
```

Build and run the containerized heavy-analysis path locally:

```bash
docker build -t commitscope:dev .
docker run --rm -e COMMITSCOPE_CONFIG=/app/examples/config.dev.json commitscope:dev
```

Generate only the local summary and SQL from previously written datasets:

```bash
PYTHONPATH=src python -m commitscope.main report --config examples/config.dev.json
```

## Repo Layout

```text
src/commitscope/         Python pipeline code
infrastructure/terraform Terraform for dev AWS resources
tests/                   Unit tests
docs/                    Metric contract and architecture notes
examples/                Example config
```

## Metric Notes

The metric semantics intentionally follow the notebooks in [docs/metric_contract.md](/Users/efeon/commitscope/docs/metric_contract.md). Python, Java, JavaScript, and TypeScript all use AST-backed structural analysis. Higher-level metrics such as `FANIN`, `FANOUT`, `CBO`, `RFC`, and `LCOM` still remain static approximations rather than full compiler-grade semantic resolution.

## Test Status

The current suite covers the pipeline, handlers, storage, reporting, DDL generation, QuickSight asset generation, repository helpers, CLI behavior, and representative parser edge cases.

Run it locally with:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

## Athena DDL

Running the pipeline also emits concrete Glue/Athena DDL into `outputs/generated/curated/glue_ddl.sql`, alongside example Athena queries in `outputs/generated/curated/athena_queries.sql`.

## QuickSight

The reporting layer emits QuickSight-ready dashboard and dataset definitions into:

- `outputs/generated/curated/quicksight_datasets.json`
- `outputs/generated/curated/quicksight_dashboard.json`
- `outputs/generated/curated/runtime_manifest.json`

The dev environment also includes a provisioning helper:

```bash
.venv/bin/python scripts/provision_quicksight.py
```

That script creates or updates:

- the Athena data source `commitscope-athena`
- the direct-query datasets:
  - `commitscope-dev-commit-summary`
  - `commitscope-dev-class-metrics`
  - `commitscope-dev-file-metrics`
- the analysis `CommitScope Dev Overview`
- the dashboard `CommitScope Dev Overview`

After a successful Step Functions execution, the state machine starts the Glue
crawler automatically. Because the QuickSight datasets use direct query against
Athena, new data becomes queryable in QuickSight after the crawler refreshes
the partitions. You can keep editing the generated analysis and dashboard in
the QuickSight UI, but the baseline QuickSight assets now exist in AWS.

## AWS Deployment

The exact dev deployment flow is documented in [aws_deploy.md](/Users/efeon/commitscope/docs/aws_deploy.md).
The exact manual-only execution flow is documented in [manual_execution.md](/Users/efeon/commitscope/docs/manual_execution.md).

Minimal cloud run sequence:

1. set GitHub repo secrets:
   - `AWS_GITHUB_ACTIONS_ROLE_ARN`
   - `AWS_ACCOUNT_ID`
2. set GitHub repo variables:
   - `TF_BUCKET_NAME`
   - `TF_ATHENA_DATABASE`
   - `TF_ECR_REPOSITORY_NAME`
   - `TF_SUBNET_IDS_JSON`
   - `TF_SECURITY_GROUP_IDS_JSON`
   - `TF_STATE_BUCKET`
   - `TF_STATE_KEY`
3. trigger [deploy-dev.yml](/Users/efeon/commitscope/.github/workflows/deploy-dev.yml)
4. generate a Step Functions input payload:

```bash
PYTHONPATH=src .venv/bin/python -m commitscope.main dispatch --config examples/config.dev.json > stepfunctions-input.json
```

5. start the state machine:

```bash
aws stepfunctions start-execution \
  --region eu-west-2 \
  --state-machine-arn "$(terraform -chdir=infrastructure/terraform/envs/dev output -raw state_machine_arn)" \
  --input file://stepfunctions-input.json
```

6. verify:
   - Step Functions execution succeeded
   - Lambda logs exist
   - ECS task reached `STOPPED`
   - Parquet exists under `s3://commitscope-nick-dev/processed/`
   - Athena can query `commitscope_dev.commit_summary`
   - QuickSight assets are provisioned and query the Athena-backed datasets
