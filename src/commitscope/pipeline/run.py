from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path

from commitscope.analysis.metrics import analyze_repository_snapshot
from commitscope.config import AppConfig
from commitscope.git.repository import clone_or_update_repository, checkout_commit, repo_name_from_url, restore_branch, select_commits
from commitscope.reporting.manifest import write_runtime_manifest
from commitscope.reporting.reporting import write_reporting_artifacts
from commitscope.storage.s3 import delete_prefixes_from_s3, upload_directory_to_s3
from commitscope.storage.writers import write_processed_outputs, write_raw_commit_payload
from commitscope.utils.fs import ensure_dir


def run_pipeline(config: AppConfig) -> dict[str, Path]:
    _reset_output_root(Path(config.output_root))
    if config.storage.write_s3:
        delete_prefixes_from_s3(
            config.storage.s3_bucket,
            [
                config.storage.prefixes.raw,
                config.storage.prefixes.processed,
                config.storage.prefixes.curated,
            ],
            config.aws_region,
        )

    repo_path = clone_or_update_repository(config.repo)
    commits = select_commits(repo_path, config.repo)
    repo_name = repo_name_from_url(config.repo.url)

    raw_root = ensure_dir(config.output_root / "raw" / repo_name)
    tables: dict[str, list[dict]] = {
        "commits": [],
        "class_metrics": [],
        "method_metrics": [],
        "file_metrics": [],
        "commit_summary": [],
    }

    try:
        for commit in commits:
            checkout_commit(repo_path, commit.commit_hash)
            commit_date = commit.timestamp.date().isoformat()
            analysis = analyze_repository_snapshot(
                repo_root=repo_path,
                commit_hash=commit.commit_hash,
                repo_name=repo_name,
                branch=config.repo.branch,
                commit_date=commit_date,
            )
            raw_payload = {
                "commit": asdict(commit),
                "class_metrics": analysis.class_metrics,
                "method_metrics": analysis.method_metrics,
                "file_metrics": analysis.file_metrics,
                "commit_summary": analysis.commit_summary,
            }
            write_raw_commit_payload(raw_root, commit.commit_hash, raw_payload)
            tables["commits"].append(
                {
                    "repo": repo_name,
                    "branch": config.repo.branch,
                    "commit_hash": commit.commit_hash,
                    "commit_date": commit_date,
                    "timestamp": commit.timestamp.isoformat(),
                    "author": commit.author,
                    "author_email": commit.author_email,
                    "message": commit.message,
                    "files_changed": commit.files_changed,
                    "insertions": commit.insertions,
                    "deletions": commit.deletions,
                }
            )
            tables["class_metrics"].extend(analysis.class_metrics)
            tables["method_metrics"].extend(analysis.method_metrics)
            tables["file_metrics"].extend(analysis.file_metrics)
            tables["commit_summary"].append(analysis.commit_summary)
    finally:
        restore_branch(repo_path, config.repo.branch)

    processed_paths = write_processed_outputs(config, tables)
    report_paths = write_reporting_artifacts(config, tables)
    outputs = {**processed_paths, **report_paths}
    outputs["runtime_manifest"] = write_runtime_manifest(config, outputs)
    if config.storage.write_s3:
        upload_directory_to_s3(config.output_root, config.storage.s3_bucket, "", config.aws_region)
    return outputs


def _reset_output_root(output_root: Path) -> None:
    if output_root.exists():
        shutil.rmtree(output_root)
    ensure_dir(output_root)
