import tempfile
from pathlib import Path

from commitscope.analysis.metrics import analyze_repository_snapshot


def test_python_metrics_are_generated_for_simple_class() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.py").write_text(
            "class A:\n"
            "    def first(self, value):\n"
            "        if value:\n"
            "            return 1\n"
            "        return 0\n",
            encoding="utf-8",
        )
        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )
        assert result.class_metrics
        assert result.method_metrics
        assert result.commit_summary["total_classes"] == 1
