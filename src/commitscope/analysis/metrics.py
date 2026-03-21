from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from commitscope.analysis.languages import language_for_file


@dataclass(slots=True)
class AnalysisResult:
    class_metrics: list[dict]
    method_metrics: list[dict]
    file_metrics: list[dict]
    commit_summary: dict


class PythonAnalyzer(ast.NodeVisitor):
    def __init__(self, module_name: str, known_classes: dict[str, list[str]]) -> None:
        self.module_name = module_name
        self.known_classes = known_classes
        self.class_metrics: dict[str, dict] = {}
        self.current_class: str | None = None
        self.current_function: str | None = None
        self.method_fanin_sources: dict[str, set[str]] = defaultdict(set)
        self.method_definitions: defaultdict[str, list[str]] = defaultdict(list)
        self.method_call_targets: dict[str, set[str]] = defaultdict(set)
        self.class_fanin_sources: dict[str, set[str]] = defaultdict(set)

    def seed_method_definitions(self, tree: ast.AST) -> None:
        class_stack: list[str] = []

        class Collector(ast.NodeVisitor):
            def __init__(self, outer: PythonAnalyzer) -> None:
                self.outer = outer

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                class_stack.append(node.name)
                self.generic_visit(node)
                class_stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                owner = ".".join(class_stack) if class_stack else "<module>"
                qualified = f"{self.outer.module_name}.{owner}.{node.name}"
                self.outer.method_definitions[node.name].append(qualified)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self.visit_FunctionDef(node)

        Collector(self).visit(tree)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous_class = self.current_class
        class_name = f"{self.module_name}.{node.name}"
        self.current_class = class_name
        self.class_metrics.setdefault(
            class_name,
            {
                "class_name": class_name,
                "wmc": 0,
                "lcom": 0.0,
                "fanin": 0,
                "fanout": 0,
                "cbo": 0,
                "rfc": 0,
                "language": "python",
                "methods": {},
            },
        )

        method_access: dict[str, set[str]] = {}
        external_classes: set[str] = set()
        directly_called_methods: set[str] = set()

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.current_function = item.name
                method_key = self._method_key(node.name, item.name)
                self.class_metrics[class_name]["methods"][method_key] = {
                    "method_name": method_key,
                    "class_name": class_name,
                    "cc": 1,
                    "loc": self._compute_loc(item),
                    "lloc": self._compute_lloc(item),
                    "parameters": self._parameter_count(item),
                    "fanin": 0,
                    "fanout": sum(1 for child in ast.walk(item) if isinstance(child, ast.Call)),
                    "language": "python",
                }
                method_access[method_key] = self._collect_instance_variables(item)
                external_classes.update(self._collect_coupled_classes(item))
                directly_called_methods.update(self._collect_direct_calls(item))
                self.generic_visit(item)
                self.current_function = None
            elif isinstance(item, ast.ClassDef):
                self.visit(item)

        method_values = self.class_metrics[class_name]["methods"].values()
        self.class_metrics[class_name]["wmc"] = sum(method["cc"] for method in method_values)
        self.class_metrics[class_name]["lcom"] = self._compute_lcom(method_access)
        self.class_metrics[class_name]["fanout"] = sum(method["fanout"] for method in method_values)
        self.class_metrics[class_name]["cbo"] = len({target for target in external_classes if target != class_name})
        self.class_metrics[class_name]["rfc"] = len({name.rsplit(".", maxsplit=1)[-1] for name in method_access}) + len(directly_called_methods)

        self.current_class = previous_class

    def visit_If(self, node: ast.If) -> None:
        self._increase_complexity()
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._increase_complexity()
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._increase_complexity()
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        for _ in node.handlers:
            self._increase_complexity()
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.current_class and self.current_function:
            caller = self._method_key(self.current_class.rsplit(".", maxsplit=1)[-1], self.current_function)
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
            if callee_name:
                for target_method in self.method_definitions.get(callee_name, []):
                    if target_method != caller:
                        self.method_fanin_sources[target_method].add(caller)
                        self.method_call_targets[caller].add(target_method)
                for target_class in self.known_classes.get(callee_name, []):
                    if target_class != self.current_class:
                        self.class_fanin_sources[target_class].add(self.current_class)
        self.generic_visit(node)

    def finalize(self) -> tuple[list[dict], list[dict]]:
        class_rows: list[dict] = []
        method_rows: list[dict] = []
        for class_name, payload in self.class_metrics.items():
            payload["fanin"] = len(self.class_fanin_sources.get(class_name, set()))
            class_rows.append({k: v for k, v in payload.items() if k != "methods"})
            for method_name, method_payload in payload["methods"].items():
                method_payload["fanin"] = len(self.method_fanin_sources.get(method_name, set()))
                method_rows.append(method_payload)
        return class_rows, method_rows

    def _increase_complexity(self, increment: int = 1) -> None:
        if self.current_class and self.current_function:
            method_name = self._method_key(self.current_class.rsplit(".", maxsplit=1)[-1], self.current_function)
            self.class_metrics[self.current_class]["methods"][method_name]["cc"] += increment

    def _method_key(self, class_name: str, method_name: str) -> str:
        return f"{self.module_name}.{class_name}.{method_name}"

    def _compute_loc(self, node: ast.AST) -> int:
        return (node.end_lineno - node.lineno + 1) if hasattr(node, "end_lineno") else 1

    def _compute_lloc(self, node: ast.AST) -> int:
        body = getattr(node, "body", [])
        return sum(1 for child in body if not isinstance(child, ast.Pass)) or 1

    def _parameter_count(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        positional = list(node.args.args)
        if positional and positional[0].arg == "self":
            positional = positional[1:]
        return len(positional) + len(node.args.kwonlyargs) + int(node.args.vararg is not None) + int(node.args.kwarg is not None)

    def _collect_instance_variables(self, node: ast.AST) -> set[str]:
        instance_vars: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == "self":
                instance_vars.add(child.attr)
        return instance_vars

    def _compute_lcom(self, method_access: dict[str, set[str]]) -> float:
        pairs = [(left, right) for index, left in enumerate(method_access) for right in list(method_access)[index + 1 :]]
        p = 0
        q = 0
        for left, right in pairs:
            if method_access[left] & method_access[right]:
                q += 1
            else:
                p += 1
        return max((p - q) / (p + q), 0) if (p + q) > 0 else 0.0

    def _collect_coupled_classes(self, node: ast.AST) -> set[str]:
        coupled: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    coupled.update(self.known_classes.get(child.func.id, []))
                elif isinstance(child.func, ast.Attribute):
                    coupled.update(self.known_classes.get(child.func.attr, []))
        return coupled

    def _collect_direct_calls(self, node: ast.AST) -> set[str]:
        calls: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)
        return calls


def analyze_repository_snapshot(repo_root: Path, commit_hash: str, repo_name: str, branch: str, commit_date: str) -> AnalysisResult:
    python_trees: dict[str, ast.AST] = {}
    file_metrics: list[dict] = []
    known_classes: dict[str, list[str]] = defaultdict(list)

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(repo_root).as_posix()
        language = language_for_file(relative)
        file_payload = _basic_file_metrics(path, relative, language, repo_name, branch, commit_hash, commit_date)
        file_metrics.append(file_payload)
        if language == "python":
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (UnicodeDecodeError, SyntaxError):
                continue
            python_trees[relative] = tree
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    known_classes[node.name].append(f"{relative}.{node.name}")

    class_rows: list[dict] = []
    method_rows: list[dict] = []
    for module_name, tree in python_trees.items():
        analyzer = PythonAnalyzer(module_name=module_name, known_classes=known_classes)
        analyzer.seed_method_definitions(tree)
        analyzer.visit(tree)
        module_classes, module_methods = analyzer.finalize()
        class_rows.extend(_annotate_rows(module_classes, repo_name, branch, commit_hash, commit_date))
        method_rows.extend(_annotate_rows(module_methods, repo_name, branch, commit_hash, commit_date))

    summary = {
        "repo": repo_name,
        "branch": branch,
        "commit_hash": commit_hash,
        "commit_date": commit_date,
        "total_classes": len(class_rows),
        "total_methods": len(method_rows),
        "avg_wmc": _average([row["wmc"] for row in class_rows]),
        "avg_lcom": _average([row["lcom"] for row in class_rows]),
        "max_cc": max((row["cc"] for row in method_rows), default=0),
        "total_loc": sum(row["loc"] for row in method_rows) + sum(row["loc"] for row in file_metrics if row["language"] != "python"),
        "total_files": len(file_metrics),
        "python_files": sum(1 for row in file_metrics if row["language"] == "python"),
        "non_python_files": sum(1 for row in file_metrics if row["language"] != "python"),
    }
    return AnalysisResult(class_rows, method_rows, file_metrics, summary)


def _basic_file_metrics(path: Path, relative: str, language: str, repo_name: str, branch: str, commit_hash: str, commit_date: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    lines = text.splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    branch_tokens = len(re.findall(r"\b(if|for|while|case|catch|switch)\b|&&|\|\|", text))
    call_tokens = len(re.findall(r"\w+\s*\(", text))
    return {
        "repo": repo_name,
        "branch": branch,
        "commit_hash": commit_hash,
        "commit_date": commit_date,
        "file_path": relative,
        "language": language,
        "loc": len(lines),
        "lloc": len(non_empty_lines),
        "complexity_signal": branch_tokens + 1 if non_empty_lines else 0,
        "fanout_signal": call_tokens,
    }


def _annotate_rows(rows: list[dict], repo_name: str, branch: str, commit_hash: str, commit_date: str) -> list[dict]:
    for row in rows:
        row["repo"] = repo_name
        row["branch"] = branch
        row["commit_hash"] = commit_hash
        row["commit_date"] = commit_date
    return rows


def _average(values: list[float | int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)
