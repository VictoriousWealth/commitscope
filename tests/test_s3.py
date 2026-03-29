from pathlib import Path

from commitscope.storage.s3 import delete_prefixes_from_s3, upload_directory_to_s3


def test_upload_directory_to_s3_uploads_all_files_with_clean_prefix(tmp_path, monkeypatch) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "root.txt").write_text("root", encoding="utf-8")
    (tmp_path / "nested" / "child.txt").write_text("child", encoding="utf-8")
    uploads: list[tuple[str, str, str]] = []

    class FakeClient:
        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            uploads.append((filename, bucket, key))

    monkeypatch.setattr("commitscope.storage.s3.boto3.client", lambda service, region_name=None: FakeClient())

    upload_directory_to_s3(tmp_path, "demo-bucket", "/prefix/", "eu-west-2")

    assert sorted(uploads) == sorted([
        (str(tmp_path / "nested" / "child.txt"), "demo-bucket", "prefix/nested/child.txt"),
        (str(tmp_path / "root.txt"), "demo-bucket", "prefix/root.txt"),
    ])


def test_upload_directory_to_s3_uses_relative_keys_without_prefix(tmp_path, monkeypatch) -> None:
    (tmp_path / "only.txt").write_text("content", encoding="utf-8")
    uploads: list[tuple[str, str, str]] = []

    class FakeClient:
        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            uploads.append((filename, bucket, key))

    monkeypatch.setattr("commitscope.storage.s3.boto3.client", lambda service, region_name=None: FakeClient())

    upload_directory_to_s3(tmp_path, "demo-bucket", "", "eu-west-2")

    assert uploads == [(str(tmp_path / "only.txt"), "demo-bucket", "only.txt")]


def test_delete_prefixes_from_s3_deletes_all_listed_objects_in_batches(monkeypatch) -> None:
    deleted_batches: list[tuple[str, list[str]]] = []

    class FakePaginator:
        def paginate(self, Bucket: str, Prefix: str):
            if Prefix == "raw/":
                yield {"Contents": [{"Key": "raw/a.json"}, {"Key": "raw/b.json"}]}
            elif Prefix == "processed/":
                yield {"Contents": [{"Key": "processed/a.parquet"}]}
            else:
                yield {}

    class FakeClient:
        def get_paginator(self, name: str):
            assert name == "list_objects_v2"
            return FakePaginator()

        def delete_objects(self, Bucket: str, Delete: dict) -> None:
            deleted_batches.append((Bucket, [item["Key"] for item in Delete["Objects"]]))

    monkeypatch.setattr("commitscope.storage.s3.boto3.client", lambda service, region_name=None: FakeClient())

    delete_prefixes_from_s3("demo-bucket", ["raw", "processed", "curated"], "eu-west-2")

    assert deleted_batches == [
        ("demo-bucket", ["raw/a.json", "raw/b.json"]),
        ("demo-bucket", ["processed/a.parquet"]),
    ]
