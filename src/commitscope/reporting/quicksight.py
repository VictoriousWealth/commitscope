from __future__ import annotations

import json
from pathlib import Path

from commitscope.config import AppConfig


def write_quicksight_assets(config: AppConfig, output_root: Path) -> dict[str, Path]:
    dataset_path = output_root / "quicksight_datasets.json"
    dashboard_path = output_root / "quicksight_dashboard.json"

    dataset_path.write_text(json.dumps(_dataset_definition(config), indent=2), encoding="utf-8")
    dashboard_path.write_text(json.dumps(_dashboard_definition(config), indent=2), encoding="utf-8")
    return {"quicksight_datasets": dataset_path, "quicksight_dashboard": dashboard_path}


def _dataset_definition(config: AppConfig) -> dict:
    prefix = config.quicksight.dataset_prefix
    db = config.athena_database
    return {
        "athena_database": db,
        "datasets": [
            {
                "dataset_id": f"{prefix}_commit_summary",
                "table": f"{db}.commit_summary",
                "import_mode": "DIRECT_QUERY",
                "description": "Trend metrics over analysed commits",
            },
            {
                "dataset_id": f"{prefix}_class_metrics",
                "table": f"{db}.class_metrics",
                "import_mode": "DIRECT_QUERY",
                "description": "Class-level hotspots and maintainability signals",
            },
            {
                "dataset_id": f"{prefix}_file_metrics",
                "table": f"{db}.file_metrics",
                "import_mode": "DIRECT_QUERY",
                "description": "Language and file footprint breakdown",
            },
        ],
    }


def _dashboard_definition(config: AppConfig) -> dict:
    prefix = config.quicksight.dataset_prefix
    return {
        "dashboard_name": config.quicksight.dashboard_name,
        "datasets": [
            f"{prefix}_commit_summary",
            f"{prefix}_class_metrics",
            f"{prefix}_file_metrics",
        ],
        "sheets": [
            {
                "name": "Evolution Overview",
                "visuals": [
                    "avg_wmc_by_commit_date_line",
                    "peak_cc_by_commit_date_line",
                    "total_loc_by_commit_date_bar",
                ],
            },
            {
                "name": "Hotspots",
                "visuals": [
                    "class_wmc_fanin_scatter",
                    "class_cbo_table",
                    "language_loc_pie",
                ],
            },
        ],
        "notes": "Template definition for QuickSight. Bind to the Athena datasets emitted by CommitScope.",
    }
