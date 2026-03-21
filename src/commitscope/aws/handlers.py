from __future__ import annotations

from commitscope.config import load_config
from commitscope.pipeline.run import run_pipeline


def run_pipeline_handler(event: dict, _context: object) -> dict:
    config_path = event["config_path"]
    config = load_config(config_path)
    outputs = run_pipeline(config)
    return {"outputs": {name: str(path) for name, path in outputs.items()}}
