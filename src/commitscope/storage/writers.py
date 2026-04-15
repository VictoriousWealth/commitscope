from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from commitscope.config import AppConfig
from commitscope.utils.fs import ensure_dir


TABLE_ORDER = ("commits", "class_metrics", "method_metrics", "file_metrics", "commit_summary")


def write_raw_commit_payload(raw_root: Path, commit_hash: str, payload: dict) -> None:
    destination = ensure_dir(raw_root / commit_hash)
    with (destination / "raw_metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def write_processed_outputs(config: AppConfig, tables: dict[str, list[dict]]) -> dict[str, Path]:
    output_root = ensure_dir(config.output_root)
    processed_root = ensure_dir(output_root / "processed")
    paths: dict[str, Path] = {}

    for table_name in TABLE_ORDER:
        rows = tables.get(table_name, [])
        frame = pd.DataFrame(rows)
        table_root = ensure_dir(processed_root / table_name)
        paths[table_name] = table_root
        if frame.empty:
            continue
        if config.storage.write_local_json:
            frame.to_json(table_root / f"{table_name}.json", orient="records", indent=2)
        if config.storage.write_local_csv:
            frame.to_csv(table_root / f"{table_name}.csv", index=False)
        if config.storage.write_local_parquet:
            _write_partitioned_parquet(frame, table_root)

    return paths


def _write_partitioned_parquet(frame: pd.DataFrame, table_root: Path) -> None:
    for (repo, branch, execution_id, commit_hash, commit_date), subset in frame.groupby(
        ["repo", "branch", "execution_id", "commit_hash", "commit_date"], dropna=False
    ):
        partition_root = ensure_dir(
            table_root
            / f"repo={repo}"
            / f"branch={branch}"
            / f"execution_id={execution_id}"
            / f"commit_hash={commit_hash}"
            / f"commit_date={commit_date}"
        )
        drop_columns = [
            column
            for column in ("repo", "branch", "execution_id", "commit_hash", "commit_date")
            if column in subset.columns
        ]
        subset.drop(columns=drop_columns).to_parquet(partition_root / "data.parquet", index=False)
