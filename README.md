# CommitScope

CommitScope turns Git history into queryable code-health datasets and dashboards. It deploys an AWS pipeline with Terraform, runs analysis in ECS via Step Functions, stores raw and processed outputs in S3, catalogs them with Glue, queries them with Athena, and visualizes them in QuickSight.

## Case Study

CommitScope is my strongest cloud/platform project. I built it to show how repository analysis can move through a real AWS data pipeline instead of staying as a local script.

- Problem: turn Git history and code-health metrics into queryable, dashboard-ready data.
- Build: GitHub Actions and Terraform deploy the AWS environment; Step Functions orchestrates the workflow; ECS Fargate runs repository analysis; S3 stores raw, processed and curated outputs; Glue catalogs datasets; Athena queries them; QuickSight visualizes the results.
- Evidence: the repo includes screenshots for deployment, Step Functions execution, ECS success, S3 outputs, Glue crawler runs, Athena query results and QuickSight dashboards.
- Main lesson: a useful cloud project needs orchestration, traceable data flow, reproducible outputs and a dashboard story, not just AWS service names.

## What Works

- GitHub Actions deploys the dev environment in AWS
- Step Functions runs the analysis pipeline end-to-end
- ECS Fargate executes the analysis container successfully
- outputs are written to S3 under `raw/`, `processed/`, and `curated/`
- Glue catalogs the generated datasets
- Athena queries the processed metrics
- QuickSight dashboards read the Athena-backed datasets directly
- each cloud execution now carries an explicit `execution_id`
- QuickSight dashboards are scoped to the latest execution rather than an inferred latest repo snapshot
- Step Functions reruns QuickSight provisioning automatically after the Glue crawler is ready
- the automated local test suite currently passes from the repo root with `.venv/bin/python -m pytest -q`

## Architecture

`GitHub Actions -> Terraform -> Step Functions -> Lambda -> ECS Fargate -> S3 -> Glue -> Athena -> QuickSight`

## Evidence

### Deployment

![GitHub Actions deploy success](docs/screenshots/github-actions-deploy-success-preview-screenshot.png)
![GitHub Actions deploy details](docs/screenshots/github-actions-deploy-success-detailed-screenshot.png)

### Workflow Execution

![Step Functions execution success](docs/screenshots/step-functions-execution-success.png)
![Step Functions state graph](docs/screenshots/aws-state-machine-pipeline-graph.png)
![ECS task exit code 0](docs/screenshots/ecs-task-exit-code-0-screenshot.png)

### Data Outputs

![S3 output prefixes](docs/screenshots/s3-outputs-bucket-viewing-screenshot.png)
![S3 curated outputs](docs/screenshots/s3-outputs-bucket-viewing-curated-folder-screenshot.png)
![Glue crawler successful runs](docs/screenshots/glue-crawler-list-of-succssful-runs-screenshot.png)
![Athena query results](docs/screenshots/athena-query-results-screenshot.png)

### Dashboards

![QuickSight repository trends](docs/screenshots/quicksight-repository-trends-screenshot.png)
![QuickSight class hotspots](docs/screenshots/quicksight-classes-hotspots-screenshot.png)
![QuickSight method hotspots](docs/screenshots/quicksight-methods-hotspots-screenshot.png)

## Metrics

The pipeline computes and exposes:

- `WMC`
- `LCOM`
- `CC`
- `FANIN`
- `FANOUT`
- `CBO`
- `RFC`
- `LOC`
- `LLOC`
- commit-level repository summaries

Metric semantics and approximations are documented in [metric_contract.md](docs/metric_contract.md).

## Language Support

- Python: AST-backed class and method analysis
- Java: AST-backed class and method analysis via `JavaParser`
- JavaScript: AST-backed class and method analysis via `@babel/parser`
- TypeScript: AST-backed class and method analysis via `ts-morph`
- Go: parser-backed struct and method analysis via `tree-sitter-go`
- Rust: parser-backed `struct` / `impl` method analysis via `tree-sitter-rust`
- C#: parser-backed class and method analysis via `tree-sitter-c-sharp`
- other languages: file-level summaries where supported by the language mapper

## Testing

Run the full local suite with:

```bash
.venv/bin/python -m pytest -q
```

Run that command from the repository root. If you `cd src` first, pytest will not discover the top-level `tests/` directory.

## Implementation Evidence

- Terraform orchestration: [main.tf](infrastructure/terraform/envs/dev/main.tf)
- QuickSight provisioning automation: [provision_quicksight.py](scripts/provision_quicksight.py)
- Manual operating procedure: [manual_execution.md](docs/manual_execution.md)
- Container run notes: [container_run.md](docs/container_run.md)

## Docs

- manual execution: [manual_execution.md](docs/manual_execution.md)
- AWS deployment: [aws_deploy.md](docs/aws_deploy.md)
- metric contract: [metric_contract.md](docs/metric_contract.md)
- original project/product write-up: [PRD.md](PRD.md)
