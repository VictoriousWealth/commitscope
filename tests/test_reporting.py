from pathlib import Path

from commitscope.config import load_config
from commitscope.reporting.manifest import write_runtime_manifest
from commitscope.reporting.reporting import write_reporting_artifacts


def test_write_runtime_manifest_serializes_outputs(tmp_path) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path)
    config.runtime.execution_id = "run-20260415T100000Z-abc12345"
    config.runtime.execution_started_at = "2026-04-15T10:00:00Z"
    (tmp_path / "curated").mkdir(parents=True)

    manifest = write_runtime_manifest(config, {"summary": tmp_path / "curated" / "summary.md"})

    payload = manifest.read_text(encoding="utf-8")
    assert '"project": "commitscope"' in payload
    assert '"execution_id": "run-20260415T100000Z-abc12345"' in payload
    assert '"summary"' in payload


def test_write_reporting_artifacts_writes_summary_sql_and_ddl(tmp_path, monkeypatch) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path)

    quicksight_manifest = tmp_path / "curated" / "quicksight_dashboard.json"

    def fake_write_quicksight_assets(_config, output_root: Path) -> dict[str, Path]:
        quicksight_manifest.write_text("{}", encoding="utf-8")
        return {"quicksight_dashboard": quicksight_manifest}

    monkeypatch.setattr("commitscope.reporting.reporting.write_quicksight_assets", fake_write_quicksight_assets)

    tables = {
        "commit_summary": [
            {
                "repo": "repo",
                "branch": "main",
                "commit_hash": "abc123",
                "commit_date": "2026-03-22",
                "total_classes": 2,
                "total_methods": 3,
                "avg_wmc": 1.5,
                "avg_lcom": 0.5,
                "max_cc": 7,
                "total_loc": 100,
                "total_files": 4,
                "python_files": 2,
                "non_python_files": 2,
            }
        ],
        "class_metrics": [
            {
                "repo": "repo",
                "branch": "main",
                "commit_hash": "abc123",
                "commit_date": "2026-03-22",
                "class_name": "Example",
                "wmc": 10,
                "fanin": 4,
                "cbo": 2,
                "rfc": 9,
                "lcom": 0.2,
                "language": "python",
                "loc": 20,
            }
        ],
    }

    outputs = write_reporting_artifacts(config, tables)

    assert outputs["summary"].exists()
    assert outputs["sql"].exists()
    assert outputs["ddl"].exists()
    assert outputs["quicksight_dashboard"].exists()
    summary_text = outputs["summary"].read_text(encoding="utf-8")
    assert "Latest Snapshot" in summary_text
    assert "Hotspot Classes" in summary_text
