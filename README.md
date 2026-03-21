# CommitScope

CommitScope is an AWS-first analytics pipeline that turns Git history into queryable code-health datasets. The MVP clones a public GitHub repository, walks a configurable commit range, computes notebook-aligned static-analysis heuristics, writes JSON/CSV/Parquet outputs locally and to S3, and prepares Athena-backed datasets for QuickSight.

## MVP Scope

- GitHub URL input for public repositories
- Configurable commit range via branch, `max_commits`, `since`, `until`, `from_commit`, and `to_commit`
- Local outputs in JSON, CSV, and Parquet
- S3 outputs under `raw/`, `processed/`, and `curated/`
- Athena-ready datasets partitioned by `repo`, `branch`, and `commit_date`
- Terraform scaffold for `eu-west-2` dev infrastructure
- ECS Fargate scaffold for heavy analysis jobs
- GitHub Actions CI

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Run the pipeline with the example config:

```bash
PYTHONPATH=src python -m commitscope.main run --config examples/config.dev.json
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

The metric semantics intentionally follow the notebooks in [docs/metric_contract.md](/Users/efeon/commitscope/docs/metric_contract.md). Python class and method metrics use static AST heuristics. Non-Python files are included in cross-language file summaries and commit-level aggregates using lightweight textual heuristics rather than full semantic parsers.

## Athena DDL

Running the pipeline also emits concrete Glue/Athena DDL into `outputs/generated/curated/glue_ddl.sql`, alongside example Athena queries in `outputs/generated/curated/athena_queries.sql`.
