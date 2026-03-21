from __future__ import annotations

from dataclasses import dataclass

from commitscope.config import AppConfig


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    columns: list[tuple[str, str]]


CORE_TABLES = [
    TableSpec(
        name="commits",
        columns=[
            ("timestamp", "string"),
            ("author", "string"),
            ("author_email", "string"),
            ("message", "string"),
            ("files_changed", "int"),
            ("insertions", "int"),
            ("deletions", "int"),
        ],
    ),
    TableSpec(
        name="class_metrics",
        columns=[
            ("class_name", "string"),
            ("wmc", "int"),
            ("lcom", "double"),
            ("fanin", "int"),
            ("fanout", "int"),
            ("cbo", "int"),
            ("rfc", "int"),
            ("language", "string"),
        ],
    ),
    TableSpec(
        name="method_metrics",
        columns=[
            ("class_name", "string"),
            ("method_name", "string"),
            ("cc", "int"),
            ("loc", "int"),
            ("lloc", "int"),
            ("parameters", "int"),
            ("fanin", "int"),
            ("fanout", "int"),
            ("language", "string"),
        ],
    ),
    TableSpec(
        name="file_metrics",
        columns=[
            ("file_path", "string"),
            ("language", "string"),
            ("loc", "int"),
            ("lloc", "int"),
            ("complexity_signal", "int"),
            ("fanout_signal", "int"),
        ],
    ),
    TableSpec(
        name="commit_summary",
        columns=[
            ("total_classes", "int"),
            ("total_methods", "int"),
            ("avg_wmc", "double"),
            ("avg_lcom", "double"),
            ("max_cc", "int"),
            ("total_loc", "int"),
            ("total_files", "int"),
            ("python_files", "int"),
            ("non_python_files", "int"),
        ],
    ),
]


def build_glue_ddl(config: AppConfig) -> str:
    database = config.athena_database
    bucket = config.storage.s3_bucket
    processed_prefix = config.storage.prefixes.processed.strip("/")
    statements = [f"CREATE DATABASE IF NOT EXISTS {database};", ""]

    for table in CORE_TABLES:
        columns = ",\n  ".join(f"{name} {dtype}" for name, dtype in table.columns)
        location = f"s3://{bucket}/{processed_prefix}/{table.name}/"
        statements.append(
            f"""CREATE EXTERNAL TABLE IF NOT EXISTS {database}.{table.name} (
  {columns}
)
PARTITIONED BY (
  repo string,
  branch string,
  commit_hash string,
  commit_date string
)
STORED AS PARQUET
LOCATION '{location}';

MSCK REPAIR TABLE {database}.{table.name};
"""
        )

    return "\n".join(statements).strip() + "\n"
