import json

from commitscope.config import load_config
from commitscope.reporting.quicksight import write_quicksight_assets
from scripts.provision_quicksight import build_latest_scope_sql


def test_write_quicksight_assets_writes_dataset_and_dashboard_files(tmp_path) -> None:
    config = load_config("examples/config.dev.json")

    outputs = write_quicksight_assets(config, tmp_path)

    dataset_payload = json.loads(outputs["quicksight_datasets"].read_text(encoding="utf-8"))
    dashboard_payload = json.loads(outputs["quicksight_dashboard"].read_text(encoding="utf-8"))

    assert dataset_payload["athena_database"] == "commitscope_dev"
    assert dataset_payload["datasets"][0]["dataset_id"] == "commitscope_dev_commit_summary"
    assert dashboard_payload["dashboard_name"] == "CommitScope Dev Dashboard"
    assert "commitscope_dev_class_metrics" in dashboard_payload["datasets"]
    assert dashboard_payload["sheets"][0]["name"] == "Evolution Overview"


def test_build_latest_scope_sql_limits_dataset_to_latest_repo_branch() -> None:
    sql = build_latest_scope_sql("commitscope_dev", "class_metrics")

    assert "WITH latest_scope AS" in sql
    assert "FROM commitscope_dev.commit_summary" in sql
    assert "FROM commitscope_dev.class_metrics AS t" in sql
    assert "ON t.repo = latest.repo" in sql
    assert "AND t.branch = latest.branch" in sql
    assert "LIMIT 1" in sql
