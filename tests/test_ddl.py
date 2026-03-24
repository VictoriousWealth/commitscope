from commitscope.aws.ddl import build_glue_ddl
from commitscope.config import load_config


def test_build_glue_ddl_contains_database_tables_and_locations() -> None:
    config = load_config("examples/config.dev.json")

    ddl = build_glue_ddl(config)

    assert "CREATE DATABASE IF NOT EXISTS commitscope_dev;" in ddl
    assert "CREATE EXTERNAL TABLE IF NOT EXISTS commitscope_dev.commits" in ddl
    assert "CREATE EXTERNAL TABLE IF NOT EXISTS commitscope_dev.class_metrics" in ddl
    assert "LOCATION 's3://commitscope-nick-dev/processed/commits/'" in ddl
    assert "MSCK REPAIR TABLE commitscope_dev.commit_summary;" in ddl

