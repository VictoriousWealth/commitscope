from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import javalang
from javalang.tokenizer import LexerError

from commitscope.analysis.languages import language_for_file


@dataclass(slots=True)
class AnalysisResult:
    class_metrics: list[dict]
    method_metrics: list[dict]
    file_metrics: list[dict]
    commit_summary: dict


JAVA_LANGUAGE = "java"
SUPPORTED_C_STYLE_LANGUAGES = {"javascript", "typescript"}


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


@dataclass(slots=True)
class TextMethod:
    class_name: str
    method_name: str
    method_simple_name: str
    language: str
    body: str
    loc: int
    lloc: int
    parameters: int
    fanout: int
    cc: int
    instance_vars: set[str]
    direct_calls: set[str]
    class_refs: set[str]


@dataclass(slots=True)
class TextClass:
    class_name: str
    language: str
    methods: list[TextMethod]


class JavaAnalyzer:
    def __init__(self, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.relative_path = relative_path
        self.source = source
        self.known_class_names = known_class_names
        self._line_offsets = self._build_line_offsets(source)

    def analyze(self) -> tuple[list[dict], list[dict]]:
        try:
            tree = javalang.parse.parse(self.source)
        except (javalang.parser.JavaSyntaxError, IndexError, TypeError, StopIteration, LexerError):
            return [], []

        classes: list[TextClass] = []
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            qualified = f"{self.relative_path}.{node.name}"
            methods: list[TextMethod] = []
            for method in list(node.methods) + list(node.constructors):
                methods.append(self._build_method(node.name, qualified, method))
            classes.append(TextClass(class_name=qualified, language=JAVA_LANGUAGE, methods=methods))
        return self._rows_from_classes(classes)

    def _rows_from_classes(self, classes: list[TextClass]) -> tuple[list[dict], list[dict]]:
        method_callers: dict[str, set[str]] = defaultdict(set)
        class_fanin_sources: dict[str, set[str]] = defaultdict(set)
        method_index = {
            method.method_simple_name: [candidate for candidate in text_class.methods if candidate.method_simple_name == method.method_simple_name]
            for text_class in classes
            for method in text_class.methods
        }

        for text_class in classes:
            for method in text_class.methods:
                caller = method.method_name
                for target in method.direct_calls:
                    for candidate in method_index.get(target, []):
                        if candidate.method_name != caller:
                            method_callers[candidate.method_name].add(caller)
                            class_fanin_sources[candidate.class_name].add(method.class_name)

        class_rows: list[dict] = []
        method_rows: list[dict] = []
        for text_class in classes:
            lcom_sources = {method.method_name: method.instance_vars for method in text_class.methods}
            class_rows.append(
                {
                    "class_name": text_class.class_name,
                    "wmc": sum(method.cc for method in text_class.methods),
                    "lcom": self._compute_lcom(lcom_sources),
                    "fanin": len(class_fanin_sources.get(text_class.class_name, set())),
                    "fanout": sum(method.fanout for method in text_class.methods),
                    "cbo": len({ref for method in text_class.methods for ref in method.class_refs if ref != text_class.class_name}),
                    "rfc": len({method.method_simple_name for method in text_class.methods}) + len({call for method in text_class.methods for call in method.direct_calls}),
                    "language": text_class.language,
                }
            )
            for method in text_class.methods:
                method_rows.append(
                    {
                        "class_name": text_class.class_name,
                        "method_name": method.method_name,
                        "cc": method.cc,
                        "loc": method.loc,
                        "lloc": method.lloc,
                        "parameters": method.parameters,
                        "fanin": len(method_callers.get(method.method_name, set())),
                        "fanout": method.fanout,
                        "language": method.language,
                    }
                )
        return class_rows, method_rows

    def _build_method(
        self,
        class_name: str,
        qualified_class_name: str,
        method: javalang.tree.MethodDeclaration | javalang.tree.ConstructorDeclaration,
    ) -> TextMethod:
        method_simple_name = method.name
        snippet = self._node_snippet(method)
        loc = snippet.count("\n") + 1 if snippet else max(len(method.body or []) + 1, 1)
        lines = [line for line in snippet.splitlines() if line.strip()]
        invocations = [node for _, node in method if isinstance(node, javalang.tree.MethodInvocation)]
        references = [node for _, node in method if isinstance(node, javalang.tree.ReferenceType)]
        cc = 1 + sum(
            1
            for _, node in method
            if isinstance(
                node,
                (
                    javalang.tree.IfStatement,
                    javalang.tree.ForStatement,
                    javalang.tree.WhileStatement,
                    javalang.tree.DoStatement,
                    javalang.tree.SwitchStatementCase,
                    javalang.tree.CatchClause,
                    javalang.tree.TernaryExpression,
                ),
            )
        )
        cc += len(re.findall(r"&&|\|\|", snippet))
        return TextMethod(
            class_name=qualified_class_name,
            method_name=f"{qualified_class_name}.{method_simple_name}",
            method_simple_name=method_simple_name,
            language=JAVA_LANGUAGE,
            body=snippet,
            loc=loc,
            lloc=len(lines) or 1,
            parameters=len(method.parameters),
            fanout=len(invocations),
            cc=cc,
            instance_vars=set(re.findall(r"\bthis\.([A-Za-z_]\w*)", snippet)),
            direct_calls={node.member for node in invocations if node.member},
            class_refs={
                f"{self.relative_path}.{node.name}"
                for node in references
                if getattr(node, "name", None) in self.known_class_names
            },
        )

    def _node_snippet(self, method: javalang.tree.MethodDeclaration | javalang.tree.ConstructorDeclaration) -> str:
        if method.position is None:
            return ""
        line_start_index = self._line_offsets[method.position.line - 1]
        open_brace = self.source.find("{", line_start_index)
        if open_brace == -1:
            return ""
        close_brace = _find_matching_brace(self.source, open_brace)
        if close_brace == -1:
            return ""
        return self.source[line_start_index : close_brace + 1]

    def _compute_lcom(self, method_access: dict[str, set[str]]) -> float:
        methods = list(method_access)
        pairs = [(left, right) for index, left in enumerate(methods) for right in methods[index + 1 :]]
        p = 0
        q = 0
        for left, right in pairs:
            if method_access[left] & method_access[right]:
                q += 1
            else:
                p += 1
        return max((p - q) / (p + q), 0) if (p + q) > 0 else 0.0

    def _build_line_offsets(self, source: str) -> list[int]:
        offsets = [0]
        running = 0
        for line in source.splitlines(keepends=True):
            running += len(line)
            offsets.append(running)
        return offsets


class CStyleAnalyzer:
    def __init__(self, language: str, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.language = language
        self.relative_path = relative_path
        self.source = source
        self.known_class_names = known_class_names

    def analyze(self) -> tuple[list[dict], list[dict]]:
        classes = self._extract_classes()
        if not classes:
            return [], []

        method_callers: dict[str, set[str]] = defaultdict(set)
        class_fanin_sources: dict[str, set[str]] = defaultdict(set)

        class_rows: list[dict] = []
        method_rows: list[dict] = []

        method_index = {
            method.method_simple_name: [candidate for candidate in text_class.methods if candidate.method_simple_name == method.method_simple_name]
            for text_class in classes
            for method in text_class.methods
        }

        for text_class in classes:
            for method in text_class.methods:
                caller = method.method_name
                for target in method.direct_calls:
                    for candidate in method_index.get(target, []):
                        if candidate.method_name != caller:
                            method_callers[candidate.method_name].add(caller)
                            class_fanin_sources[candidate.class_name].add(method.class_name)

        for text_class in classes:
            lcom_sources = {method.method_name: method.instance_vars for method in text_class.methods}
            class_rows.append(
                {
                    "class_name": text_class.class_name,
                    "wmc": sum(method.cc for method in text_class.methods),
                    "lcom": self._compute_lcom(lcom_sources),
                    "fanin": len(class_fanin_sources.get(text_class.class_name, set())),
                    "fanout": sum(method.fanout for method in text_class.methods),
                    "cbo": len({ref for method in text_class.methods for ref in method.class_refs if ref != text_class.class_name}),
                    "rfc": len({method.method_simple_name for method in text_class.methods}) + len({call for method in text_class.methods for call in method.direct_calls}),
                    "language": text_class.language,
                }
            )
            for method in text_class.methods:
                method_rows.append(
                    {
                        "class_name": text_class.class_name,
                        "method_name": method.method_name,
                        "cc": method.cc,
                        "loc": method.loc,
                        "lloc": method.lloc,
                        "parameters": method.parameters,
                        "fanin": len(method_callers.get(method.method_name, set())),
                        "fanout": method.fanout,
                        "language": text_class.language,
                    }
                )
        return class_rows, method_rows

    def _extract_classes(self) -> list[TextClass]:
        class_pattern = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
        classes: list[TextClass] = []
        for match in class_pattern.finditer(self.source):
            class_name = match.group(1)
            open_brace = self.source.find("{", match.end())
            if open_brace == -1:
                continue
            close_brace = _find_matching_brace(self.source, open_brace)
            if close_brace == -1:
                continue
            body = self.source[open_brace + 1 : close_brace]
            qualified = f"{self.relative_path}.{class_name}"
            methods = self._extract_methods(body, qualified, class_name)
            classes.append(TextClass(class_name=qualified, language=self.language, methods=methods))
        return classes

    def _extract_methods(self, class_body: str, qualified_class_name: str, class_name: str) -> list[TextMethod]:
        methods: list[TextMethod] = []
        method_pattern = _method_pattern_for_language(self.language, class_name)
        for match in method_pattern.finditer(class_body):
            method_simple_name = match.group("name")
            params = match.group("params") or ""
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace == -1:
                continue
            close_brace = _find_matching_brace(class_body, open_brace)
            if close_brace == -1:
                continue
            body = class_body[open_brace + 1 : close_brace]
            loc = body.count("\n") + 2
            meaningful_lines = [line for line in body.splitlines() if line.strip() and line.strip() not in {"{", "}"}]
            methods.append(
                TextMethod(
                    class_name=qualified_class_name,
                    method_name=f"{qualified_class_name}.{method_simple_name}",
                    method_simple_name=method_simple_name,
                    language=self.language,
                    body=body,
                    loc=loc,
                    lloc=len(meaningful_lines) or 1,
                    parameters=_parameter_count_from_text(params),
                    fanout=len(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body)),
                    cc=_complexity_from_text(body),
                    instance_vars=set(re.findall(r"\bthis\.([A-Za-z_]\w*)", body)),
                    direct_calls=set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body)),
                    class_refs={f"{self.relative_path}.{ref}" for ref in self.known_class_names if ref in re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b", body)},
                )
            )
        return methods

    def _compute_lcom(self, method_access: dict[str, set[str]]) -> float:
        methods = list(method_access)
        pairs = [(left, right) for index, left in enumerate(methods) for right in methods[index + 1 :]]
        p = 0
        q = 0
        for left, right in pairs:
            if method_access[left] & method_access[right]:
                q += 1
            else:
                p += 1
        return max((p - q) / (p + q), 0) if (p + q) > 0 else 0.0


def analyze_repository_snapshot(repo_root: Path, commit_hash: str, repo_name: str, branch: str, commit_date: str) -> AnalysisResult:
    python_trees: dict[str, ast.AST] = {}
    text_sources: dict[str, tuple[str, str]] = {}
    file_metrics: list[dict] = []
    known_classes: dict[str, list[str]] = defaultdict(list)
    known_text_class_names: set[str] = set()

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
        elif language == JAVA_LANGUAGE:
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text_sources[relative] = (language, source)
            for class_name in re.findall(r"\bclass\s+([A-Za-z_]\w*)", source):
                known_text_class_names.add(class_name)
        elif language in SUPPORTED_C_STYLE_LANGUAGES:
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text_sources[relative] = (language, source)
            for class_name in re.findall(r"\bclass\s+([A-Za-z_]\w*)", source):
                known_text_class_names.add(class_name)

    class_rows: list[dict] = []
    method_rows: list[dict] = []
    for module_name, tree in python_trees.items():
        analyzer = PythonAnalyzer(module_name=module_name, known_classes=known_classes)
        analyzer.seed_method_definitions(tree)
        analyzer.visit(tree)
        module_classes, module_methods = analyzer.finalize()
        class_rows.extend(_annotate_rows(module_classes, repo_name, branch, commit_hash, commit_date))
        method_rows.extend(_annotate_rows(module_methods, repo_name, branch, commit_hash, commit_date))
    for relative, (language, source) in text_sources.items():
        analyzer = (
            JavaAnalyzer(relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == JAVA_LANGUAGE
            else CStyleAnalyzer(language=language, relative_path=relative, source=source, known_class_names=known_text_class_names)
        )
        module_classes, module_methods = analyzer.analyze()
        class_rows.extend(_annotate_rows(module_classes, repo_name, branch, commit_hash, commit_date))
        method_rows.extend(_annotate_rows(module_methods, repo_name, branch, commit_hash, commit_date))

    analyzed_method_languages = {"python", JAVA_LANGUAGE, *SUPPORTED_C_STYLE_LANGUAGES}

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
        "total_loc": sum(row["loc"] for row in method_rows) + sum(row["loc"] for row in file_metrics if row["language"] not in analyzed_method_languages),
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


def _find_matching_brace(text: str, open_brace_index: int) -> int:
    depth = 0
    for index in range(open_brace_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _method_pattern_for_language(language: str, class_name: str) -> re.Pattern[str]:
    if language == "java":
        return re.compile(
            r"(?:public|protected|private|static|final|synchronized|abstract|\s)+"
            r"(?:[A-Za-z_<>\[\],?]+\s+)?(?P<name>" + re.escape(class_name) + r"|[A-Za-z_]\w*)\s*"
            r"\((?P<params>[^)]*)\)\s*\{",
            re.MULTILINE,
        )
    return re.compile(
        r"(?:public|protected|private|static|async|get|set|readonly|override|abstract|\s)*"
        r"(?P<name>constructor|[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*(?::[^{=]+)?\s*\{",
        re.MULTILINE,
    )


def _parameter_count_from_text(params: str) -> int:
    cleaned = [param.strip() for param in params.split(",") if param.strip()]
    return len(cleaned)


def _complexity_from_text(body: str) -> int:
    branch_tokens = len(re.findall(r"\b(if|for|while|case|catch|switch|else\s+if)\b|&&|\|\|", body))
    return branch_tokens + 1 if body.strip() else 0
