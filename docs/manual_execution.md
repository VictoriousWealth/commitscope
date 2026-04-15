# Manual Execution Runbook

This is the exact manual-only flow for running CommitScope in the dev AWS environment in `eu-west-2`.

## Current Dev Resources

- State machine:
  - `arn:aws:states:eu-west-2:463470943939:stateMachine:commitscope-dev-pipeline`
- S3 bucket:
  - `s3://commitscope-nick-dev`
- Glue database:
  - `commitscope_dev`
- Athena workgroup:
  - `commitscope-dev-wg`
- ECS cluster:
  - `arn:aws:ecs:eu-west-2:463470943939:cluster/commitscope-dev-cluster`

## What The Pipeline Writes

The pipeline writes these output categories to S3.

Important behavior: each new cloud execution clears the previous `raw/`, `processed/`, and `curated/` objects before uploading the new repo snapshot. The QuickSight dashboard is therefore intended to show the latest run by default rather than accumulate multiple repos unless you change the pipeline behavior again.

The pipeline writes these output categories to S3:

- Raw commit payloads:
  - `s3://commitscope-nick-dev/raw/`
- Processed partitioned parquet:
  - `s3://commitscope-nick-dev/processed/`
- Curated reporting artifacts:
  - `s3://commitscope-nick-dev/curated/`

Examples from a successful run:

- `s3://commitscope-nick-dev/raw/MechanicalSoup/<commit-hash>/raw_metrics.json`
- `s3://commitscope-nick-dev/processed/commits/repo=MechanicalSoup/branch=main/commit_hash=<hash>/commit_date=<date>/data.parquet`
- `s3://commitscope-nick-dev/curated/runtime_manifest.json`
- `s3://commitscope-nick-dev/curated/summary.md`
- `s3://commitscope-nick-dev/curated/glue_ddl.sql`
- `s3://commitscope-nick-dev/curated/athena_queries.sql`
- `s3://commitscope-nick-dev/curated/quicksight_datasets.json`
- `s3://commitscope-nick-dev/curated/quicksight_dashboard.json`

## 1. Deploy The Latest Code

Push your current branch to `main`, then trigger [deploy-dev.yml](/Users/efeon/commitscope/.github/workflows/deploy-dev.yml).

That workflow does this:

1. applies Terraform for the base infrastructure
2. builds the Docker image
3. pushes the image to ECR
4. applies Terraform again with the new image URI

Wait for `deploy-dev.yml` to finish successfully before starting an execution.

## 2. Use This Step Functions Input Payload

Use this payload unless you intentionally want to change the target repo. If you prefer to generate it from the example config instead of copy-pasting JSON, run:

```bash
.venv/bin/python -m commitscope.main dispatch --config examples/config.dev.json > stepfunctions-input.json
```

The payload should look like this:

```json
{
  "project": "commitscope",
  "environment": "dev",
  "config_json": {
    "project": "commitscope",
    "environment": "dev",
    "aws_region": "eu-west-2",
    "athena_database": "commitscope_dev",
    "repo": {
      "url": "https://github.com/MechanicalSoup/MechanicalSoup.git",
      "branch": "main",
      "max_commits": 10,
      "since": null,
      "until": null,
      "from_commit": null,
      "to_commit": null,
      "checkout_root": "data/repos"
    },
    "storage": {
      "s3_bucket": "commitscope-nick-dev",
      "prefixes": {
        "raw": "raw",
        "processed": "processed",
        "curated": "curated"
      },
      "write_local_json": false,
      "write_local_csv": false,
      "write_local_parquet": true,
      "write_s3": true
    },
    "reporting": {
      "output_root": "outputs/generated"
    },
    "runtime": {
      "execution_mode": "stepfunctions",
      "container_image": null,
      "container_command": null,
      "state_machine_arn": "arn:aws:states:eu-west-2:463470943939:stateMachine:commitscope-dev-pipeline"
    },
    "quicksight": {
      "dashboard_name": "CommitScope Dev Dashboard",
      "dataset_prefix": "commitscope_dev"
    }
  }
}
```

If you want a faster smoke test, reduce:

```json
"max_commits": 3
```

## 3. Start An Execution

Save the payload as `stepfunctions-input.json`, then run:

```bash
aws stepfunctions start-execution \
  --region eu-west-2 \
  --state-machine-arn arn:aws:states:eu-west-2:463470943939:stateMachine:commitscope-dev-pipeline \
  --input file://stepfunctions-input.json
```

Important:

- always start a fresh execution after a new deploy
- do not rely on retrying old failed executions after task definition changes

## 4. Check Execution Status

List recent executions:

```bash
aws stepfunctions list-executions \
  --region eu-west-2 \
  --state-machine-arn arn:aws:states:eu-west-2:463470943939:stateMachine:commitscope-dev-pipeline \
  --max-results 10
```

Describe one execution:

```bash
aws stepfunctions describe-execution \
  --region eu-west-2 \
  --execution-arn <EXECUTION_ARN>
```

## 5. Check ECS If The Execution Fails

List stopped tasks:

```bash
aws ecs list-tasks \
  --region eu-west-2 \
  --cluster arn:aws:ecs:eu-west-2:463470943939:cluster/commitscope-dev-cluster \
  --desired-status STOPPED
```

Describe a task:

```bash
aws ecs describe-tasks \
  --region eu-west-2 \
  --cluster arn:aws:ecs:eu-west-2:463470943939:cluster/commitscope-dev-cluster \
  --tasks <TASK_ARN>
```

Read the container logs:

```bash
aws logs tail /ecs/commitscope-dev \
  --region eu-west-2 \
  --since 30m
```

## 6. Verify S3 Outputs

Check the newest objects:

```bash
aws s3api list-objects-v2 \
  --region eu-west-2 \
  --bucket commitscope-nick-dev \
  --query 'reverse(sort_by(Contents,&LastModified))[:30].[LastModified,Size,Key]' \
  --output table
```

Check processed and curated objects only:

```bash
aws s3api list-objects-v2 \
  --region eu-west-2 \
  --bucket commitscope-nick-dev \
  --query 'Contents[?starts_with(Key, `processed/`) || starts_with(Key, `curated/`)].[LastModified,Size,Key]' \
  --output table
```

## 7. Verify Glue

After a successful Step Functions run, the state machine starts the crawler automatically. Check its current state with:

```bash
aws glue get-crawler \
  --region eu-west-2 \
  --name commitscope-dev-crawler
```

If you need to force a manual refresh, start the crawler:

```bash
aws glue start-crawler \
  --region eu-west-2 \
  --name commitscope-dev-crawler
```

List discovered Glue tables:

```bash
aws glue get-tables \
  --region eu-west-2 \
  --database-name commitscope_dev \
  --query 'TableList[].Name' \
  --output table
```

List partitions for the `commits` table:

```bash
aws glue get-partitions \
  --region eu-west-2 \
  --database-name commitscope_dev \
  --table-name commits \
  --max-results 10 \
  --query 'Partitions[].Values' \
  --output table
```

## 8. Verify Athena

Show tables:

```bash
aws athena start-query-execution \
  --region eu-west-2 \
  --work-group commitscope-dev-wg \
  --query-string "SHOW TABLES IN commitscope_dev"
```

Count commit rows:

```bash
aws athena start-query-execution \
  --region eu-west-2 \
  --work-group commitscope-dev-wg \
  --query-string "SELECT count(*) AS commit_rows FROM commitscope_dev.commits"
```

Then fetch results with the returned `QueryExecutionId`:

```bash
aws athena get-query-results \
  --region eu-west-2 \
  --query-execution-id <QUERY_EXECUTION_ID> \
  --output table
```

## 9. QuickSight Status

Current status in this AWS account:

- the pipeline generates QuickSight definition files under `s3://commitscope-nick-dev/curated/`
- QuickSight is enabled in the account
- Athena data source `commitscope-athena` exists in `eu-west-2`
- these direct-query datasets exist in `eu-west-2`:
  - `commitscope-dev-commit-summary`
  - `commitscope-dev-class-metrics`
  - `commitscope-dev-file-metrics`
- analysis `CommitScope Dev Overview` exists in `eu-west-2`
- dashboard `CommitScope Dev Overview` exists in `eu-west-2`
- the state machine starts the Glue crawler automatically after the ECS task succeeds
- the state machine now reruns QuickSight provisioning after the crawler is ready

Provision or refresh the QuickSight data source, datasets, analysis, and dashboard manually with:

```bash
.venv/bin/python scripts/provision_quicksight.py
```

What is automatic now:

- Step Functions runs the analysis container
- Step Functions starts the Glue crawler
- Glue refreshes Athena partitions
- Step Functions reruns QuickSight provisioning after the crawler is ready
- QuickSight datasets use direct query, so fresh Athena data is visible without a separate dataset ingestion step

What is still manual:

- refining the visual layout if you want something more polished than the baseline dashboard
- adding more visuals, filters, themes, or access controls in the QuickSight console

So QuickSight is now working for the MVP. The remaining QuickSight work is improvement work, not unblocker work.

## 10. What To Change For A Real Repo

To analyse a different public repository, change only this block in the payload:

```json
"repo": {
  "url": "https://github.com/<owner>/<repo>.git",
  "branch": "main",
  "max_commits": 10,
  "since": null,
  "until": null,
  "from_commit": null,
  "to_commit": null,
  "checkout_root": "data/repos"
}
```

## 11. Current Definition Of Done

This project is working as an MVP when all of these are true:

1. `deploy-dev.yml` succeeds
2. a fresh Step Functions execution succeeds
3. raw, processed, and curated files land in S3
4. Glue crawler succeeds
5. Athena can query the discovered tables
6. QuickSight datasets can query the Athena-backed tables
7. the baseline QuickSight dashboard loads successfully
