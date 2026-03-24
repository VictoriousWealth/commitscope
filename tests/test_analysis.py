import tempfile
from pathlib import Path

from commitscope.analysis.metrics import (
    _complexity_from_text,
    _find_matching_brace,
    _method_pattern_for_language,
    analyze_repository_snapshot,
)


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


def test_analysis_skips_invalid_python_but_keeps_other_file_metrics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "broken.py").write_text("class Broken(:\n    pass\n", encoding="utf-8")
        (repo_root / "notes.txt").write_text("hello\nworld\n", encoding="utf-8")

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        assert result.class_metrics == []
        assert result.method_metrics == []
        assert len(result.file_metrics) == 2
        assert result.commit_summary["total_files"] == 2


def test_java_constructor_and_method_are_extracted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Sample.java").write_text(
            "public class Sample {\n"
            "    private int value;\n"
            "    public Sample(int value) {\n"
            "        this.value = value;\n"
            "    }\n"
            "    public int read() {\n"
            "        return this.value;\n"
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

        method_names = {row["method_name"] for row in result.method_metrics}
        assert "Sample.java.Sample.Sample" in method_names
        assert "Sample.java.Sample.read" in method_names
        assert result.commit_summary["total_methods"] == 2


def test_java_analysis_handles_annotations_and_generics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Service.java").write_text(
            "import java.util.List;\n"
            "public class Service {\n"
            "    @Deprecated\n"
            "    public List<String> names(List<String> input) {\n"
            "        if (input == null || input.isEmpty()) {\n"
            "            return List.of();\n"
            "        }\n"
            "        return input;\n"
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

        assert any(row["class_name"] == "Service.java.Service" for row in result.class_metrics)
        method_row = next(row for row in result.method_metrics if row["method_name"] == "Service.java.Service.names")
        assert method_row["parameters"] == 1
        assert method_row["cc"] >= 3


def test_total_loc_does_not_double_count_python_or_c_style_methods() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.py").write_text(
            "class A:\n"
            "    def first(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        (repo_root / "Sample.java").write_text(
            "public class Sample {\n"
            "    public int read() {\n"
            "        return 1;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "README.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        method_loc_total = sum(row["loc"] for row in result.method_metrics)
        other_file_loc_total = sum(
            row["loc"] for row in result.file_metrics if row["language"] not in {"python", "java", "javascript", "typescript"}
        )
        assert result.commit_summary["total_loc"] == method_loc_total + other_file_loc_total


def test_find_matching_brace_handles_nested_blocks() -> None:
    text = "function x() { if (true) { return 1; } return 0; }"
    open_index = text.index("{")

    close_index = _find_matching_brace(text, open_index)

    assert close_index == len(text) - 1


def test_method_pattern_for_javascript_matches_constructor() -> None:
    pattern = _method_pattern_for_language("javascript", "Widget")
    match = pattern.search("constructor(value) { this.value = value; }")

    assert match is not None
    assert match.group("name") == "constructor"
    assert match.group("params") == "value"


def test_complexity_from_text_counts_branches_and_boolean_operators() -> None:
    body = "if (a && b) { return 1; } else if (c || d) { return 2; }"

    assert _complexity_from_text(body) == 5
