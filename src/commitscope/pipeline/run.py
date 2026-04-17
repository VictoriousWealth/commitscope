from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from commitscope.analysis.metrics import analyze_repository_snapshot
from commitscope.config import AppConfig
from commitscope.git.repository import clone_or_update_repository, checkout_commit, repo_name_from_url, restore_branch, select_commits
from commitscope.reporting.manifest import write_runtime_manifest
from commitscope.reporting.reporting import write_reporting_artifacts
from commitscope.storage.s3 import delete_prefixes_from_s3, upload_directory_to_s3
from commitscope.storage.writers import write_processed_outputs, write_raw_commit_payload
from commitscope.utils.fs import ensure_dir


def run_pipeline(config: AppConfig) -> dict[str, Path]:
    execution_id, execution_started_at = _ensure_execution_context(config)
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
    total_commits = len(commits)
    _log_progress(
        "pipeline_commits_selected",
        execution_id=execution_id,
        repo=repo_name,
        branch=config.repo.branch,
        total_commits=total_commits,
    )

    raw_root = ensure_dir(config.output_root / "raw" / repo_name)
    tables: dict[str, list[dict]] = {
        "commits": [],
        "class_metrics": [],
        "method_metrics": [],
        "file_metrics": [],
        "commit_summary": [],
    }

    try:
        for index, commit in enumerate(commits, start=1):
            commit_started = perf_counter()
            _log_progress(
                "commit_analysis_started",
                execution_id=execution_id,
                repo=repo_name,
                branch=config.repo.branch,
                commit_index=index,
                total_commits=total_commits,
                commit_hash=commit.commit_hash,
                commit_date=commit.timestamp.date().isoformat(),
                files_changed=commit.files_changed,
            )
            checkout_commit(repo_path, commit.commit_hash)
            commit_date = commit.timestamp.date().isoformat()
            analysis = analyze_repository_snapshot(
                repo_root=repo_path,
                commit_hash=commit.commit_hash,
                repo_name=repo_name,
                branch=config.repo.branch,
                commit_date=commit_date,
            )
            _annotate_execution_rows(analysis.class_metrics, execution_id, execution_started_at)
            _annotate_execution_rows(analysis.method_metrics, execution_id, execution_started_at)
            _annotate_execution_rows(analysis.file_metrics, execution_id, execution_started_at)
            analysis.commit_summary["execution_id"] = execution_id
            analysis.commit_summary["execution_started_at"] = execution_started_at
            raw_payload = {
                "execution_id": execution_id,
                "execution_started_at": execution_started_at,
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
                    "execution_id": execution_id,
                    "execution_started_at": execution_started_at,
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
            _log_progress(
                "commit_analysis_completed",
                execution_id=execution_id,
                repo=repo_name,
                branch=config.repo.branch,
                commit_index=index,
                total_commits=total_commits,
                commit_hash=commit.commit_hash,
                duration_seconds=round(perf_counter() - commit_started, 3),
                class_rows=len(analysis.class_metrics),
                method_rows=len(analysis.method_metrics),
                file_rows=len(analysis.file_metrics),
            )
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


def _ensure_execution_context(config: AppConfig) -> tuple[str, str]:
    if config.runtime.execution_started_at is None:
        config.runtime.execution_started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if config.runtime.execution_id is None:
        timestamp = config.runtime.execution_started_at.replace(":", "").replace("-", "").replace(".", "")
        config.runtime.execution_id = f"run-{timestamp}-{uuid4().hex[:8]}"
    return config.runtime.execution_id, config.runtime.execution_started_at


def _annotate_execution_rows(rows: list[dict], execution_id: str, execution_started_at: str) -> None:
    for row in rows:
        row["execution_id"] = execution_id
        row["execution_started_at"] = execution_started_at


def _log_progress(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)
