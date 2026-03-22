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


def test_java_metrics_are_generated_for_simple_class() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Sample.java").write_text(
            "public class Sample {\n"
            "    public int first(int value) {\n"
            "        if (value > 0) {\n"
            "            return 1;\n"
            "        }\n"
            "        return 0;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )
        assert any(row["language"] == "java" for row in result.class_metrics)
        assert any(row["language"] == "java" for row in result.method_metrics)


def test_javascript_metrics_are_generated_for_simple_class() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.js").write_text(
            "class Sample {\n"
            "  first(value) {\n"
            "    if (value) {\n"
            "      return 1;\n"
            "    }\n"
            "    return 0;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )
        assert any(row["language"] == "javascript" for row in result.class_metrics)
        assert any(row["language"] == "javascript" for row in result.method_metrics)


def test_typescript_metrics_are_generated_for_simple_class() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.ts").write_text(
            "class Sample {\n"
            "  first(value: number): number {\n"
            "    if (value > 0) {\n"
            "      return 1;\n"
            "    }\n"
            "    return 0;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )
        assert any(row["language"] == "typescript" for row in result.class_metrics)
        assert any(row["language"] == "typescript" for row in result.method_metrics)
