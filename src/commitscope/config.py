from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RepoConfig:
    url: str
    branch: str
    max_commits: int
    since: str | None = None
    until: str | None = None
    from_commit: str | None = None
    to_commit: str | None = None
    checkout_root: str = "data/repos"


@dataclass(slots=True)
class PrefixConfig:
    raw: str = "raw"
    processed: str = "processed"
    curated: str = "curated"


@dataclass(slots=True)
class StorageConfig:
    s3_bucket: str
    prefixes: PrefixConfig
    write_local_json: bool = True
    write_local_csv: bool = True
    write_local_parquet: bool = True
    write_s3: bool = False


@dataclass(slots=True)
class ReportingConfig:
    output_root: str = "outputs/generated"


@dataclass(slots=True)
class AppConfig:
    project: str
    environment: str
    aws_region: str
    athena_database: str
    repo: RepoConfig
    storage: StorageConfig
    reporting: ReportingConfig

    @property
    def output_root(self) -> Path:
        return Path(self.reporting.output_root)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: str | Path) -> AppConfig:
    raw = _read_json(Path(path))
    repo = RepoConfig(**raw["repo"])
    prefixes = PrefixConfig(**raw["storage"].get("prefixes", {}))
    storage = StorageConfig(prefixes=prefixes, **{k: v for k, v in raw["storage"].items() if k != "prefixes"})
    reporting = ReportingConfig(**raw.get("reporting", {}))
    return AppConfig(
        project=raw["project"],
        environment=raw["environment"],
        aws_region=raw["aws_region"],
        athena_database=raw["athena_database"],
        repo=repo,
        storage=storage,
        reporting=reporting,
    )
