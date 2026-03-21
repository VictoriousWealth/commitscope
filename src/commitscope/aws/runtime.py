from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from commitscope.config import AppConfig, load_config


def build_stepfunctions_input(config: AppConfig) -> dict:
    config_json = json.dumps(asdict(config))
    return {
        "execution_mode": "stepfunctions",
        "config_json": config_json,
        "repo_url": config.repo.url,
        "branch": config.repo.branch,
        "max_commits": config.repo.max_commits,
    }


def load_stepfunctions_input(path: str | Path) -> dict:
    return build_stepfunctions_input(load_config(path))
