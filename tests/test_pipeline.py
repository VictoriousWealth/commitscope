from datetime import datetime
from pathlib import Path

from commitscope.config import load_config
from commitscope.git.repository import CommitRecord
from commitscope.pipeline.run import run_pipeline


class DummyAnalysis:
    def __init__(self) -> None:
        self.class_metrics = [
            {
                "repo": "repository",
                "branch": "main",
                "commit_hash": "abc123",
                "commit_date": "2026-03-22",
                "class_name": "Example",
                "wmc": 5,
                "fanin": 2,
                "fanout": 1,
                "cbo": 1,
                "rfc": 3,
                "lcom": 0.1,
                "language": "python",
                "loc": 10,
            }
        ]
        self.method_metrics = [
            {
                "repo": "repository",
                "branch": "main",
                "commit_hash": "abc123",
                "commit_date": "2026-03-22",
                "class_name": "Example",
                "method_name": "work",
                "cc": 2,
                "loc": 6,
                "lloc": 5,
                "parameters": 1,
                "fanin": 1,
                "fanout": 1,
                "language": "python",
            }
        ]
        self.file_metrics = [
            {
                "repo": "repository",
                "branch": "main",
                "commit_hash": "abc123",
                "commit_date": "2026-03-22",
                "file_path": "example.py",
                "language": "python",
                "loc": 10,
                "lloc": 8,
                "complexity_signal": 2,
                "fanout_signal": 1,
            }
        ]
        self.commit_summary = {
            "repo": "repository",
            "branch": "main",
            "commit_hash": "abc123",
            "commit_date": "2026-03-22",
            "total_classes": 1,
            "total_methods": 1,
            "avg_wmc": 5,
            "avg_lcom": 0.1,
            "max_cc": 2,
            "total_loc": 10,
            "total_files": 1,
            "python_files": 1,
            "non_python_files": 0,
        }


def test_run_pipeline_uploads_after_manifest_and_restores_branch(tmp_path, monkeypatch) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path / "outputs")
    config.storage.write_s3 = True

    commit = CommitRecord(
        commit_hash="abc123",
        author="Ada",
        author_email="ada@example.com",
        timestamp=datetime.fromisoformat("2026-03-22T10:00:00"),
        message="Commit",
        files_changed=1,
        insertions=5,
        deletions=1,
    )

    calls: list[str] = []

    monkeypatch.setattr("commitscope.pipeline.run.clone_or_update_repository", lambda repo_config: tmp_path / "repo")
    monkeypatch.setattr("commitscope.pipeline.run.select_commits", lambda repo_path, repo_config: [commit])
    monkeypatch.setattr("commitscope.pipeline.run.repo_name_from_url", lambda url: "repository")
    monkeypatch.setattr("commitscope.pipeline.run.checkout_commit", lambda repo_path, commit_hash: calls.append(f"checkout:{commit_hash}"))
    monkeypatch.setattr("commitscope.pipeline.run.analyze_repository_snapshot", lambda **kwargs: DummyAnalysis())
    monkeypatch.setattr("commitscope.pipeline.run.write_raw_commit_payload", lambda *args, **kwargs: calls.append("raw"))
    monkeypatch.setattr(
        "commitscope.pipeline.run.write_processed_outputs",
        lambda config, tables: {"processed": Path(config.output_root) / "processed"},
    )
    monkeypatch.setattr(
        "commitscope.pipeline.run.write_reporting_artifacts",
        lambda config, tables: {"summary": Path(config.output_root) / "curated" / "summary.md"},
    )

    def fake_manifest(config, outputs):
        calls.append("manifest")
        return Path(config.output_root) / "curated" / "runtime_manifest.json"

    def fake_upload(root, bucket, prefix, region):
        calls.append("upload")
        assert calls[-2] == "manifest"

    monkeypatch.setattr("commitscope.pipeline.run.write_runtime_manifest", fake_manifest)
    monkeypatch.setattr("commitscope.pipeline.run.upload_directory_to_s3", fake_upload)
    monkeypatch.setattr("commitscope.pipeline.run.restore_branch", lambda repo_path, branch: calls.append(f"restore:{branch}"))

    outputs = run_pipeline(config)

    assert outputs["runtime_manifest"].name == "runtime_manifest.json"
    assert "upload" in calls
    assert calls[-1] == "upload"
    assert "restore:main" in calls
