from __future__ import annotations

import json
from pathlib import Path

from commitscope.config import AppConfig


def write_runtime_manifest(config: AppConfig, outputs: dict[str, Path]) -> Path:
    manifest_path = Path(config.output_root) / "curated" / "runtime_manifest.json"
    payload = {
        "execution_mode": config.runtime.execution_mode,
        "project": config.project,
        "environment": config.environment,
        "aws_region": config.aws_region,
        "athena_database": config.athena_database,
        "bucket": config.storage.s3_bucket,
        "repo_url": config.repo.url,
        "branch": config.repo.branch,
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path
