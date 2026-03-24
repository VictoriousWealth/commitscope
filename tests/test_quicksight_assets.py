import json

from commitscope.config import load_config
from commitscope.reporting.quicksight import write_quicksight_assets


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

