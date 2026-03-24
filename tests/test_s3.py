from pathlib import Path

from commitscope.storage.s3 import upload_directory_to_s3


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
