from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from commitscope.config import load_config, load_config_from_env
from commitscope.pipeline.run import run_pipeline


def run_pipeline_handler(event: dict, _context: object) -> dict:
    config_path = event.get("config_path", os.environ.get("COMMITSCOPE_CONFIG", "examples/config.dev.json"))
    config = load_config(config_path)
    outputs = run_pipeline(config)
    return {"outputs": {name: str(path) for name, path in outputs.items()}}


def prepare_execution_handler(event: dict, _context: object) -> dict:
    config = _config_from_event(event)
    config.runtime.execution_mode = "stepfunctions"
    container_env = [
        {"name": "COMMITSCOPE_CONFIG_JSON", "value": json.dumps(asdict(config))},
    ]
    return {
        "project": config.project,
        "environment": config.environment,
        "config_json": json.dumps(asdict(config)),
        "container_overrides": [
            {
                "name": "commitscope",
                "environment": container_env,
            }
        ],
    }


def _config_from_event(event: dict):
    if "config_json" in event:
        temp_path = Path("/tmp/commitscope-config.json")
        temp_path.write_text(json.dumps(event["config_json"] if isinstance(event["config_json"], dict) else json.loads(event["config_json"])), encoding="utf-8")
        return load_config(temp_path)
    if "config_path" in event:
        return load_config(event["config_path"])
    return load_config_from_env("examples/config.dev.json")
