from __future__ import annotations

from pathlib import Path

import pandas as pd

from commitscope.config import AppConfig
from commitscope.utils.fs import ensure_dir


def write_reporting_artifacts(config: AppConfig, tables: dict[str, list[dict]]) -> dict[str, Path]:
    output_root = ensure_dir(config.output_root / "curated")
    summary_path = output_root / "summary.md"
    sql_path = output_root / "athena_queries.sql"

    commit_summary = pd.DataFrame(tables.get("commit_summary", []))
    class_metrics = pd.DataFrame(tables.get("class_metrics", []))

    summary_path.write_text(_build_summary(commit_summary, class_metrics), encoding="utf-8")
    sql_path.write_text(_build_athena_sql(config), encoding="utf-8")
    return {"summary": summary_path, "sql": sql_path}


def _build_summary(commit_summary: pd.DataFrame, class_metrics: pd.DataFrame) -> str:
    lines = ["# CommitScope Summary", ""]
    if commit_summary.empty:
        lines.append("No commits were analysed.")
        return "\n".join(lines)

    commit_summary = commit_summary.sort_values(by="commit_date", ascending=False)
    top_spike = commit_summary.sort_values(by=["max_cc", "total_loc"], ascending=False).iloc[0]
    latest = commit_summary.iloc[0]

    lines.extend(
        [
            "## Latest Snapshot",
            f"- Commit: `{latest['commit_hash']}` on `{latest['commit_date']}`",
            f"- Total files: {int(latest['total_files'])}",
            f"- Total classes: {int(latest['total_classes'])}",
            f"- Total methods: {int(latest['total_methods'])}",
            "",
            "## Complexity Spike",
            f"- Commit: `{top_spike['commit_hash']}`",
            f"- Max CC: {top_spike['max_cc']}",
            f"- Total LOC: {top_spike['total_loc']}",
            "",
        ]
    )

    if not class_metrics.empty:
        hotspots = class_metrics.sort_values(by=["wmc", "fanin", "cbo"], ascending=False).head(5)
        lines.append("## Hotspot Classes")
        for _, row in hotspots.iterrows():
            lines.append(
                f"- `{row['class_name']}`: WMC={row['wmc']}, FANIN={row['fanin']}, CBO={row['cbo']}"
            )

    return "\n".join(lines)


def _build_athena_sql(config: AppConfig) -> str:
    bucket = config.storage.s3_bucket
    processed = config.storage.prefixes.processed.rstrip("/")
    database = config.athena_database
    return f"""CREATE DATABASE IF NOT EXISTS {database};

MSCK REPAIR TABLE {database}.class_metrics;
MSCK REPAIR TABLE {database}.method_metrics;
MSCK REPAIR TABLE {database}.file_metrics;
MSCK REPAIR TABLE {database}.commit_summary;

SELECT commit_date, avg(avg_wmc) AS avg_wmc, max(max_cc) AS peak_cc
FROM {database}.commit_summary
GROUP BY commit_date
ORDER BY commit_date;

SELECT class_name, wmc, fanin, cbo
FROM {database}.class_metrics
WHERE repo = 'YOUR_REPO'
ORDER BY wmc DESC, fanin DESC
LIMIT 20;

-- Example S3 layout for the processed datasets:
-- s3://{bucket}/{processed}/class_metrics/repo=<repo>/branch=<branch>/commit_date=<yyyy-mm-dd>/data.parquet
"""
