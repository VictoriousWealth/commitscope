from __future__ import annotations

from pathlib import Path

import boto3


def upload_directory_to_s3(root: Path, bucket: str, prefix: str, region: str) -> None:
    client = boto3.client("s3", region_name=region)
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            cleaned_prefix = prefix.strip("/")
            key = f"{cleaned_prefix}/{relative}" if cleaned_prefix else relative
            client.upload_file(str(path), bucket, key)
