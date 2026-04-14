from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from commitscope.config import load_config
from commitscope.aws.runtime import load_stepfunctions_input
from commitscope.pipeline.run import run_pipeline
from commitscope.reporting.manifest import write_runtime_manifest
from commitscope.reporting.reporting import write_reporting_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commitscope")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full pipeline")
    run_parser.add_argument("--config", required=True, help="Path to the JSON config file")

    report_parser = subparsers.add_parser("report", help="Generate reporting artifacts from local processed files")
    report_parser.add_argument("--config", required=True, help="Path to the JSON config file")

    dispatch_parser = subparsers.add_parser("dispatch", help="Generate Step Functions input for cloud execution")
    dispatch_parser.add_argument("--config", required=True, help="Path to the JSON config file")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "run":
        outputs = run_pipeline(config)
        print(json.dumps({name: str(path) for name, path in outputs.items()}, indent=2))
        return

    if args.command == "dispatch":
        payload = load_stepfunctions_input(args.config)
        print(json.dumps(payload, indent=2))
        return

    outputs = write_reporting_artifacts(config, _load_local_tables(config))
    outputs["runtime_manifest"] = write_runtime_manifest(config, outputs)
    print(json.dumps({name: str(path) for name, path in outputs.items()}, indent=2))


def _load_local_tables(config: object) -> dict[str, list[dict]]:
    processed_root = Path(config.output_root) / "processed"
    tables: dict[str, list[dict]] = {}
    for table_name in ("commit_summary", "class_metrics"):
        table_root = processed_root / table_name
        tables[table_name] = _load_local_table(table_root, table_name)
    return tables


def _load_local_table(table_root: Path, table_name: str) -> list[dict]:
    csv_path = table_root / f"{table_name}.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path).to_dict(orient="records")

    json_path = table_root / f"{table_name}.json"
    if json_path.exists():
        return pd.read_json(json_path).to_dict(orient="records")

    parquet_paths = sorted(table_root.rglob("*.parquet"))
    if parquet_paths:
        frames = [pd.read_parquet(path) for path in parquet_paths]
        if frames:
            return pd.concat(frames, ignore_index=True).to_dict(orient="records")

    return []


if __name__ == "__main__":
    main()
