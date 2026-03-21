from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from commitscope.config import load_config
from commitscope.pipeline.run import run_pipeline
from commitscope.reporting.reporting import write_reporting_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commitscope")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full pipeline")
    run_parser.add_argument("--config", required=True, help="Path to the JSON config file")

    report_parser = subparsers.add_parser("report", help="Generate reporting artifacts from local processed files")
    report_parser.add_argument("--config", required=True, help="Path to the JSON config file")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "run":
        outputs = run_pipeline(config)
        print(json.dumps({name: str(path) for name, path in outputs.items()}, indent=2))
        return

    outputs = write_reporting_artifacts(config, _load_local_tables(config))
    print(json.dumps({name: str(path) for name, path in outputs.items()}, indent=2))


def _load_local_tables(config: object) -> dict[str, list[dict]]:
    processed_root = Path(config.output_root) / "processed"
    tables: dict[str, list[dict]] = {}
    for table_name in ("commit_summary", "class_metrics"):
        csv_path = processed_root / table_name / f"{table_name}.csv"
        tables[table_name] = pd.read_csv(csv_path).to_dict(orient="records") if csv_path.exists() else []
    return tables


if __name__ == "__main__":
    main()
