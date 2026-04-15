from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from commitscope.config import AppConfig, load_config


def build_stepfunctions_input(config: AppConfig) -> dict:
    cloud_config = deepcopy(config)
    cloud_config.runtime.execution_mode = "stepfunctions"
    cloud_config.storage.write_s3 = True
    config_json = json.dumps(asdict(cloud_config))
    return {
        "execution_mode": "stepfunctions",
        "project": cloud_config.project,
        "environment": cloud_config.environment,
        "config_json": config_json,
        "repo_url": cloud_config.repo.url,
        "branch": cloud_config.repo.branch,
        "max_commits": cloud_config.repo.max_commits,
    }


def load_stepfunctions_input(path: str | Path) -> dict:
    return build_stepfunctions_input(load_config(path))
