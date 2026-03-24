import json
from dataclasses import asdict
from pathlib import Path

from commitscope.aws.handlers import prepare_execution_handler, run_pipeline_handler
from commitscope.config import load_config


def test_prepare_execution_handler_builds_stepfunctions_overrides() -> None:
    config = load_config("examples/config.dev.json")

    result = prepare_execution_handler({"config_json": asdict(config)}, None)

    config_json = json.loads(result["config_json"])
    assert result["project"] == "commitscope"
    assert result["environment"] == "dev"
    assert config_json["runtime"]["execution_mode"] == "stepfunctions"
    assert result["container_overrides"] == [
        {
            "Name": "commitscope",
            "Environment": [
                {
                    "Name": "COMMITSCOPE_CONFIG_JSON",
                    "Value": json.dumps(config_json),
                }
            ],
        }
    ]


def test_run_pipeline_handler_returns_stringified_output_paths(monkeypatch) -> None:
    config = load_config("examples/config.dev.json")

    monkeypatch.setattr("commitscope.aws.handlers.load_config", lambda path: config)
    monkeypatch.setattr(
        "commitscope.aws.handlers.run_pipeline",
        lambda loaded_config: {"summary": Path("/tmp/summary.md"), "ddl": Path("/tmp/glue_ddl.sql")},
    )

    result = run_pipeline_handler({"config_path": "examples/config.dev.json"}, None)

    assert result == {"outputs": {"summary": "/tmp/summary.md", "ddl": "/tmp/glue_ddl.sql"}}
