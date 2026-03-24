import json

from commitscope.config import load_config
from commitscope.storage.writers import write_processed_outputs, write_raw_commit_payload


def test_write_raw_commit_payload_persists_json(tmp_path) -> None:
    payload = {"commit": {"hash": "abc123"}, "class_metrics": []}

    write_raw_commit_payload(tmp_path, "abc123", payload)

    written = json.loads((tmp_path / "abc123" / "raw_metrics.json").read_text(encoding="utf-8"))
    assert written == payload


def test_write_processed_outputs_writes_partitioned_parquet_and_flat_files(tmp_path) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path)
    config.storage.write_local_json = True
    config.storage.write_local_csv = True
    config.storage.write_local_parquet = True

    tables = {
        "commits": [
            {
                "repo": "repo",
                "branch": "main",
                "commit_hash": "abc123",
                "commit_date": "2026-03-22",
                "timestamp": "2026-03-22T00:00:00",
                "author": "Ada",
                "author_email": "ada@example.com",
                "message": "Initial commit",
                "files_changed": 1,
                "insertions": 10,
                "deletions": 0,
            }
        ],
        "class_metrics": [],
        "method_metrics": [],
        "file_metrics": [],
        "commit_summary": [],
    }

    paths = write_processed_outputs(config, tables)

    commits_root = paths["commits"]
    assert (commits_root / "commits.json").exists()
    assert (commits_root / "commits.csv").exists()
    assert (
        commits_root
        / "repo=repo"
        / "branch=main"
        / "commit_hash=abc123"
        / "commit_date=2026-03-22"
        / "data.parquet"
    ).exists()

