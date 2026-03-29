from __future__ import annotations

from pathlib import Path

import boto3


def delete_prefixes_from_s3(bucket: str, prefixes: list[str], region: str) -> None:
    client = boto3.client("s3", region_name=region)
    for prefix in prefixes:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix.strip("/") + "/"):
            objects = page.get("Contents", [])
            if not objects:
                continue
            for index in range(0, len(objects), 1000):
                batch = objects[index : index + 1000]
                client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in batch]},
                )


def upload_directory_to_s3(root: Path, bucket: str, prefix: str, region: str) -> None:
    client = boto3.client("s3", region_name=region)
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            cleaned_prefix = prefix.strip("/")
            key = f"{cleaned_prefix}/{relative}" if cleaned_prefix else relative
            client.upload_file(str(path), bucket, key)
