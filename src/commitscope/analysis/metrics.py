from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_c_sharp
import tree_sitter_go
import tree_sitter_javascript
import tree_sitter_rust
import tree_sitter_typescript

from commitscope.analysis.languages import language_for_file


@dataclass(slots=True)
class AnalysisResult:
    class_metrics: list[dict]
    method_metrics: list[dict]
    file_metrics: list[dict]
    commit_summary: dict


@dataclass(slots=True)
class PythonModuleInfo:
    imported_modules: dict[str, str]
    imported_classes: dict[str, str]
    function_return_types: dict[str, str]


@dataclass(slots=True)
class PythonClassInfo:
    qualified_name: str
    module_name: str
    class_name: str
    methods: set[str]
    base_classes: set[str]
    method_return_types: dict[str, str]


@dataclass(slots=True)
class PythonProjectIndex:
    module_infos: dict[str, PythonModuleInfo]
    class_infos: dict[str, PythonClassInfo]
    classes_by_simple: dict[str, list[str]]
    classes_by_module: dict[str, dict[str, str]]


JAVA_LANGUAGE = "java"
JAVASCRIPT_LANGUAGE = "javascript"
TYPESCRIPT_LANGUAGE = "typescript"
GO_LANGUAGE = "go"
RUST_LANGUAGE = "rust"
CSHARP_LANGUAGE = "csharp"
SUPPORTED_C_STYLE_LANGUAGES = {JAVASCRIPT_LANGUAGE, TYPESCRIPT_LANGUAGE, GO_LANGUAGE, RUST_LANGUAGE, CSHARP_LANGUAGE}
REPO_ROOT = Path(__file__).resolve().parents[3]
NODE_AST_HELPER = REPO_ROOT / "scripts" / "js_ts_ast_metrics.cjs"
JAVA_HELPER_SOURCE = REPO_ROOT / "tools" / "java" / "src" / "JavaMetricsMain.java"
JAVA_HELPER_BIN = REPO_ROOT / "tools" / "java" / "bin"
JAVA_HELPER_MAIN = "JavaMetricsMain"
JAVA_PARSER_JAR = REPO_ROOT / "tools" / "java" / "lib" / "javaparser-core-3.27.1.jar"
ARG_SEPARATOR = "\x1f"
CLASS_NAME_SEPARATOR = "\x1e"
CLASS_LIST_SEPARATOR = "\x1d"
TREE_SITTER_LANGUAGES = {
    JAVASCRIPT_LANGUAGE: Language(tree_sitter_javascript.language()),
    TYPESCRIPT_LANGUAGE: Language(tree_sitter_typescript.language_typescript()),
    GO_LANGUAGE: Language(tree_sitter_go.language()),
    RUST_LANGUAGE: Language(tree_sitter_rust.language()),
    CSHARP_LANGUAGE: Language(tree_sitter_c_sharp.language()),
}


class PythonAnalyzer:
    def __init__(
        self,
        module_name: str,
        project_index: PythonProjectIndex,
        method_fanin_sources: dict[str, set[str]] | None = None,
        class_fanin_sources: dict[str, set[str]] | None = None,
    ) -> None:
        self.module_name = module_name
        self.project_index = project_index
        self.method_fanin_sources = method_fanin_sources if method_fanin_sources is not None else defaultdict(set)
        self.class_fanin_sources = class_fanin_sources if class_fanin_sources is not None else defaultdict(set)

    def analyze(self, tree: ast.AST) -> tuple[list[dict], list[dict]]:
        class_rows: list[dict] = []
        method_rows: list[dict] = []
        for node in tree.body if isinstance(tree, ast.Module) else []:
            if isinstance(node, ast.ClassDef):
                nested_class_rows, nested_method_rows = self._analyze_class_node(node)
                class_rows.extend(nested_class_rows)
                method_rows.extend(nested_method_rows)
        return class_rows, method_rows

    def _analyze_class_node(self, node: ast.ClassDef) -> tuple[list[dict], list[dict]]:
        qualified_class_name = f"{self.module_name}.{node.name}"
        class_info = self.project_index.class_infos.get(qualified_class_name)
        if class_info is None:
            return [], []

        class_rows: list[dict] = []
        method_rows: list[dict] = []
        method_payloads: dict[str, dict] = {}
        method_access: dict[str, set[str]] = {}
        external_classes: set[str] = set(class_info.base_classes)
        direct_response_methods: set[str] = set()
        class_self_attr_types = self._class_self_attribute_types(node)

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                (
                    method_payload,
                    instance_vars,
                    resolved_methods,
                    resolved_classes,
                ) = self._analyze_method_node(class_info, item, class_self_attr_types)
                method_payloads[method_payload["method_name"]] = method_payload
                method_access[method_payload["method_name"]] = instance_vars
                external_classes.update(resolved_classes)
                for target_method in resolved_methods:
                    if target_method != method_payload["method_name"]:
                        self.method_fanin_sources[target_method].add(method_payload["method_name"])
                        target_class_name = target_method.rsplit(".", maxsplit=1)[0]
                        if target_class_name != qualified_class_name:
                            self.class_fanin_sources[target_class_name].add(qualified_class_name)
                        direct_response_methods.add(target_method)
            elif isinstance(item, ast.ClassDef):
                nested_class_rows, nested_method_rows = self._analyze_class_node(item)
                class_rows.extend(nested_class_rows)
                method_rows.extend(nested_method_rows)

        class_row = {
            "class_name": qualified_class_name,
            "wmc": sum(payload["cc"] for payload in method_payloads.values()),
            "lcom": _compute_lcom(method_access),
            "fanin": 0,
            "fanout": sum(payload["fanout"] for payload in method_payloads.values()),
            "cbo": len({target for target in external_classes if target != qualified_class_name}),
            "rfc": len(class_info.methods) + len({target for target in direct_response_methods if target.rsplit(".", maxsplit=1)[0] != qualified_class_name}),
            "language": "python",
        }
        class_rows.insert(0, class_row)

        for method_name, method_payload in method_payloads.items():
            method_rows.append(method_payload)
        return class_rows, method_rows

    def _analyze_method_node(
        self,
        class_info: PythonClassInfo,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_self_attr_types: dict[str, str],
    ) -> tuple[dict, set[str], set[str], set[str]]:
        method_name = f"{class_info.qualified_name}.{node.name}"
        local_var_types = self._parameter_type_bindings(node, class_info)
        self_attr_types = dict(class_self_attr_types)
        resolved_methods: set[str] = set()
        resolved_classes: set[str] = set(class_info.base_classes)
        instance_vars = self._collect_instance_variables(node)

        class MethodResolver(ast.NodeVisitor):
            def __init__(self, outer: PythonAnalyzer) -> None:
                self.outer = outer

            def visit_Assign(self, assign_node: ast.Assign) -> None:
                inferred_type = self.outer._infer_python_expr_type(assign_node.value, class_info, local_var_types, self_attr_types)
                if inferred_type:
                    for target in assign_node.targets:
                        self.outer._bind_python_target_type(target, inferred_type, local_var_types, self_attr_types)
                self.generic_visit(assign_node)

            def visit_AnnAssign(self, assign_node: ast.AnnAssign) -> None:
                inferred_type = self.outer._infer_python_expr_type(assign_node.value, class_info, local_var_types, self_attr_types) if assign_node.value else None
                if inferred_type:
                    self.outer._bind_python_target_type(assign_node.target, inferred_type, local_var_types, self_attr_types)
                self.generic_visit(assign_node)

            def visit_Call(self, call_node: ast.Call) -> None:
                target_method, target_class = self.outer._resolve_python_call(call_node, class_info, local_var_types, self_attr_types)
                if target_method:
                    resolved_methods.add(target_method)
                    resolved_classes.add(target_method.rsplit(".", maxsplit=1)[0])
                elif target_class:
                    resolved_classes.add(target_class)
                self.generic_visit(call_node)

        MethodResolver(self).visit(node)

        payload = {
            "method_name": method_name,
            "class_name": class_info.qualified_name,
            "cc": self._python_complexity(node),
            "loc": self._compute_loc(node),
            "lloc": self._compute_lloc(node),
            "parameters": self._parameter_count(node),
            "fanin": 0,
            "fanout": sum(1 for child in ast.walk(node) if isinstance(child, ast.Call)),
            "language": "python",
        }
        return payload, instance_vars, resolved_methods, resolved_classes

    def _class_self_attribute_types(self, node: ast.ClassDef) -> dict[str, str]:
        attr_types: dict[str, str] = {}
        class_info = self.project_index.class_infos.get(f"{self.module_name}.{node.name}")
        if class_info is None:
            return attr_types
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                local_var_types: dict[str, str] = {}

                class InitResolver(ast.NodeVisitor):
                    def __init__(self, outer: PythonAnalyzer) -> None:
                        self.outer = outer

                    def visit_Assign(self, assign_node: ast.Assign) -> None:
                        inferred_type = self.outer._infer_python_expr_type(assign_node.value, class_info, local_var_types, attr_types)
                        if inferred_type:
                            for target in assign_node.targets:
                                self.outer._bind_python_target_type(target, inferred_type, local_var_types, attr_types)
                        self.generic_visit(assign_node)

                    def visit_AnnAssign(self, assign_node: ast.AnnAssign) -> None:
                        inferred_type = self.outer._infer_python_expr_type(assign_node.value, class_info, local_var_types, attr_types) if assign_node.value else None
                        if inferred_type:
                            self.outer._bind_python_target_type(assign_node.target, inferred_type, local_var_types, attr_types)
                        self.generic_visit(assign_node)

                InitResolver(self).visit(item)
        return attr_types

    def _resolve_python_call(
        self,
        node: ast.Call,
        class_info: PythonClassInfo,
        local_var_types: dict[str, str],
        self_attr_types: dict[str, str],
    ) -> tuple[str | None, str | None]:
        if isinstance(node.func, ast.Name):
            name = node.func.id
            resolved_method = self._resolve_python_method_for_class(class_info.qualified_name, name)
            if resolved_method:
                return resolved_method, resolved_method.rsplit(".", maxsplit=1)[0]
            resolved_class = self._resolve_python_class_name(name, class_info)
            if resolved_class:
                return None, resolved_class
            module_info = self.project_index.module_infos.get(class_info.module_name, PythonModuleInfo({}, {}, {}))
            function_return = module_info.function_return_types.get(name)
            if function_return:
                return None, function_return
            return None, None
        if isinstance(node.func, ast.Attribute):
            owner_class = self._resolve_python_value_type(node.func.value, class_info, local_var_types, self_attr_types)
            if owner_class:
                resolved_method = self._resolve_python_method_for_class(owner_class, node.func.attr)
                if resolved_method:
                    return resolved_method, resolved_method.rsplit(".", maxsplit=1)[0]
                return None, owner_class
            resolved_class = self._resolve_python_attribute_class(node.func.value, node.func.attr, class_info)
            if resolved_class:
                return None, resolved_class
        return None, None

    def _resolve_python_value_type(
        self,
        node: ast.AST,
        class_info: PythonClassInfo,
        local_var_types: dict[str, str],
        self_attr_types: dict[str, str],
    ) -> str | None:
        if isinstance(node, ast.Name):
            if node.id == "self":
                return class_info.qualified_name
            if node.id in local_var_types:
                return local_var_types[node.id]
            return None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            return self_attr_types.get(node.attr)
        if isinstance(node, ast.Call):
            target_method, target_class = self._resolve_python_call(node, class_info, local_var_types, self_attr_types)
            if target_method:
                method_owner = target_method.rsplit(".", maxsplit=1)[0]
                method_simple_name = target_method.rsplit(".", maxsplit=1)[-1]
                owner_info = self.project_index.class_infos.get(method_owner)
                if owner_info and method_simple_name in owner_info.method_return_types:
                    return owner_info.method_return_types[method_simple_name]
            return target_class
        if isinstance(node, ast.Subscript):
            return self._infer_python_expr_type(node.value, class_info, local_var_types, self_attr_types)
        return None

    def _resolve_python_class_name(self, name: str, class_info: PythonClassInfo) -> str | None:
        module_info = self.project_index.module_infos.get(class_info.module_name, PythonModuleInfo({}, {}, {}))
        if name in module_info.imported_classes:
            return module_info.imported_classes[name]
        module_class = self.project_index.classes_by_module.get(class_info.module_name, {}).get(name)
        if module_class:
            return module_class
        candidates = self.project_index.classes_by_simple.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _resolve_python_attribute_class(self, value: ast.AST, attr: str, class_info: PythonClassInfo) -> str | None:
        if isinstance(value, ast.Name):
            module_info = self.project_index.module_infos.get(class_info.module_name, PythonModuleInfo({}, {}, {}))
            imported_module = module_info.imported_modules.get(value.id)
            if imported_module:
                return self.project_index.classes_by_module.get(imported_module, {}).get(attr)
        return None

    def _infer_python_expr_type(
        self,
        node: ast.AST | None,
        class_info: PythonClassInfo,
        local_var_types: dict[str, str],
        self_attr_types: dict[str, str],
    ) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Call):
            _, target_class = self._resolve_python_call(node, class_info, local_var_types, self_attr_types)
            return target_class
        if isinstance(node, ast.Name):
            return local_var_types.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            return self_attr_types.get(node.attr)
        return None

    def _bind_python_target_type(
        self,
        target: ast.AST,
        inferred_type: str,
        local_var_types: dict[str, str],
        self_attr_types: dict[str, str],
    ) -> None:
        if isinstance(target, ast.Name):
            local_var_types[target.id] = inferred_type
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
            self_attr_types[target.attr] = inferred_type

    def _python_complexity(self, node: ast.AST) -> int:
        cc = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match)):
                cc += 1
            elif isinstance(child, ast.Try):
                cc += len(child.handlers)
            elif isinstance(child, ast.BoolOp):
                cc += max(len(child.values) - 1, 0)
        return cc

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

    def _parameter_type_bindings(self, node: ast.FunctionDef | ast.AsyncFunctionDef, class_info: PythonClassInfo) -> dict[str, str]:
        bindings: dict[str, str] = {}
        module_info = self.project_index.module_infos.get(class_info.module_name, PythonModuleInfo({}, {}, {}))
        for parameter in [*node.args.args, *node.args.kwonlyargs]:
            if parameter.arg == "self":
                continue
            resolved = _resolve_python_class_expression(
                parameter.annotation,
                class_info.module_name,
                module_info,
                self.project_index.classes_by_module,
                self.project_index.classes_by_simple,
            )
            if resolved:
                bindings[parameter.arg] = resolved
        return bindings

    def _resolve_python_method_for_class(self, class_name: str, method_name: str) -> str | None:
        visited: set[str] = set()
        stack = [class_name]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            info = self.project_index.class_infos.get(current)
            if info is None:
                continue
            if method_name in info.methods:
                return f"{current}.{method_name}"
            stack.extend(info.base_classes)
        return None


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


def _compute_lcom(method_access: dict[str, set[str]]) -> float:
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


def _rows_from_text_classes(classes: list[TextClass]) -> tuple[list[dict], list[dict]]:
    method_callers: dict[str, set[str]] = defaultdict(set)
    class_fanin_sources: dict[str, set[str]] = defaultdict(set)
    method_index: dict[str, list[TextMethod]] = defaultdict(list)
    methods_by_name_and_class: dict[tuple[str, str], TextMethod] = {}
    methods_by_full_name: dict[str, TextMethod] = {}

    for text_class in classes:
        for method in text_class.methods:
            method_index[method.method_simple_name].append(method)
            methods_by_name_and_class[(method.class_name, method.method_simple_name)] = method
            methods_by_full_name[method.method_name] = method

    for text_class in classes:
        for method in text_class.methods:
            caller = method.method_name
            for target in method.direct_calls:
                candidate = methods_by_full_name.get(target)
                if candidate is None:
                    candidate = methods_by_name_and_class.get((text_class.class_name, target))
                if candidate is None and "." in target:
                    target_class_name, _, method_simple_name = target.rpartition(".")
                    candidate = methods_by_name_and_class.get((target_class_name, method_simple_name))
                if candidate is None:
                    global_candidates = method_index.get(target, [])
                    candidate = global_candidates[0] if len(global_candidates) == 1 else None
                if candidate is None or candidate.method_name == caller:
                    continue
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
                "lcom": _compute_lcom(lcom_sources),
                "fanin": len(class_fanin_sources.get(text_class.class_name, set())),
                "fanout": sum(method.fanout for method in text_class.methods),
                "cbo": len({ref for method in text_class.methods for ref in method.class_refs if ref != text_class.class_name}),
                "rfc": len({method.method_simple_name for method in text_class.methods})
                + len({call for method in text_class.methods for call in method.direct_calls}),
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


class JavaAnalyzer:
    def __init__(self, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.relative_path = relative_path
        self.source = source
        self.known_class_names = known_class_names

    def extract_classes(self) -> list[TextClass]:
        return _run_java_helper(self.relative_path, self.source, self.known_class_names)

    def analyze(self) -> tuple[list[dict], list[dict]]:
        return _rows_from_text_classes(self.extract_classes())

class JavaScriptAnalyzer:
    def __init__(self, language: str, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.language = language
        self.relative_path = relative_path
        self.source = source
        self.known_class_names = known_class_names

    def extract_classes(self) -> list[TextClass]:
        return _run_node_helper(self.language, self.relative_path, self.source, self.known_class_names)

    def analyze(self) -> tuple[list[dict], list[dict]]:
        return _rows_from_text_classes(self.extract_classes())


class TypeScriptAnalyzer(JavaScriptAnalyzer):
    pass


class GoAnalyzer:
    def __init__(self, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.relative_path = relative_path
        self.source = source
        self.source_bytes = source.encode("utf-8")
        self.known_class_names = known_class_names
        self.parser = Parser(TREE_SITTER_LANGUAGES[GO_LANGUAGE])

    def extract_classes(self) -> list[TextClass]:
        tree = self.parser.parse(self.source_bytes)
        root = tree.root_node
        if root.has_error:
            return []

        structs = {
            self._text(type_spec.child_by_field_name("name")): f"{self.relative_path}.{self._text(type_spec.child_by_field_name('name'))}"
            for type_decl in _iter_nodes(root, "type_declaration")
            for type_spec in type_decl.named_children
            if type_spec.type == "type_spec"
            and type_spec.child_by_field_name("name") is not None
            and (type_node := type_spec.child_by_field_name("type")) is not None
            and type_node.type == "struct_type"
        }
        methods_by_class: dict[str, list[TextMethod]] = defaultdict(list)
        for method_node in _iter_nodes(root, "method_declaration"):
            receiver_node = method_node.child_by_field_name("receiver")
            name_node = method_node.child_by_field_name("name")
            params_node = method_node.child_by_field_name("parameters")
            body_node = method_node.child_by_field_name("body")
            if receiver_node is None or name_node is None or params_node is None or body_node is None:
                continue
            receiver_type = self._go_receiver_type(receiver_node)
            qualified_class_name = structs.get(receiver_type, f"{self.relative_path}.{receiver_type}")
            method = self._build_go_method(qualified_class_name, method_node, name_node, params_node, body_node)
            methods_by_class[qualified_class_name].append(method)
        return [TextClass(class_name=class_name, language=GO_LANGUAGE, methods=methods) for class_name, methods in methods_by_class.items()]

    def analyze(self) -> tuple[list[dict], list[dict]]:
        return self._rows_from_classes(self.extract_classes())

    def _rows_from_classes(self, classes: list[TextClass]) -> tuple[list[dict], list[dict]]:
        return _rows_from_text_classes(classes)

    def _go_receiver_type(self, receiver_node) -> str:
        for parameter in receiver_node.named_children:
            if parameter.type != "parameter_declaration":
                continue
            for child in parameter.named_children:
                if child.type == "type_identifier":
                    return self._text(child)
                if child.type == "pointer_type":
                    nested = child.named_children[-1] if child.named_children else None
                    if nested is not None:
                        return self._text(nested)
        return "Receiver"

    def _build_go_method(self, qualified_class_name: str, method_node, name_node, params_node, body_node) -> TextMethod:
        method_simple_name = self._text(name_node)
        snippet = self._text(method_node)
        body_text = self._text(body_node)
        lines = [line for line in body_text.splitlines() if line.strip()]
        receiver_name = self._go_receiver_name(method_node.child_by_field_name("receiver"))
        call_nodes = [node for node in _iter_nodes(body_node, "call_expression")]
        direct_calls = set()
        for call_node in call_nodes:
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue
            if function_node.type in {"identifier", "field_identifier"}:
                direct_calls.add(self._text(function_node))
            elif function_node.type == "selector_expression":
                field = function_node.child_by_field_name("field")
                if field is not None:
                    direct_calls.add(self._text(field))
        instance_vars = {
            self._text(field_node)
            for node in _iter_nodes(body_node, "selector_expression")
            if (operand := node.child_by_field_name("operand")) is not None
            and operand.type == "identifier"
            and self._text(operand) == receiver_name
            and (field_node := node.child_by_field_name("field")) is not None
        }
        class_refs = {
            f"{self.relative_path}.{self._text(node)}"
            for node in _iter_nodes(body_node, "type_identifier")
            if self._text(node) in self.known_class_names
        }
        cc = 1 + sum(1 for node in _iter_nodes(body_node) if node.type in {"if_statement", "for_statement", "expression_switch_statement", "type_switch_statement", "select_statement"})
        cc += len(re.findall(r"&&|\|\|", body_text))
        parameters = sum(1 for child in params_node.named_children if child.type == "parameter_declaration")
        return TextMethod(
            class_name=qualified_class_name,
            method_name=f"{qualified_class_name}.{method_simple_name}",
            method_simple_name=method_simple_name,
            language=GO_LANGUAGE,
            body=snippet,
            loc=snippet.count("\n") + 1 if snippet else 1,
            lloc=len(lines) or 1,
            parameters=parameters,
            fanout=len(call_nodes),
            cc=cc,
            instance_vars=instance_vars,
            direct_calls=direct_calls,
            class_refs=class_refs,
        )

    def _go_receiver_name(self, receiver_node) -> str:
        if receiver_node is None:
            return "self"
        for parameter in receiver_node.named_children:
            if parameter.type != "parameter_declaration":
                continue
            for child in parameter.named_children:
                if child.type == "identifier":
                    return self._text(child)
        return "self"

    def _text(self, node) -> str:
        return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8")


class RustAnalyzer:
    def __init__(self, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.relative_path = relative_path
        self.source = source
        self.source_bytes = source.encode("utf-8")
        self.known_class_names = known_class_names
        self.parser = Parser(TREE_SITTER_LANGUAGES[RUST_LANGUAGE])

    def extract_classes(self) -> list[TextClass]:
        tree = self.parser.parse(self.source_bytes)
        root = tree.root_node
        if root.has_error:
            return []

        methods_by_class: dict[str, list[TextMethod]] = defaultdict(list)
        for impl_node in _iter_nodes(root, "impl_item"):
            type_node = impl_node.child_by_field_name("type")
            body_node = impl_node.child_by_field_name("body")
            if type_node is None or body_node is None:
                continue
            class_name = self._text(type_node)
            qualified_class_name = f"{self.relative_path}.{class_name}"
            for function_node in _iter_nodes(body_node, "function_item"):
                name_node = function_node.child_by_field_name("name")
                params_node = function_node.child_by_field_name("parameters")
                fn_body_node = function_node.child_by_field_name("body")
                if name_node is None or params_node is None or fn_body_node is None:
                    continue
                methods_by_class[qualified_class_name].append(
                    self._build_rust_method(qualified_class_name, function_node, name_node, params_node, fn_body_node)
                )
        return [TextClass(class_name=class_name, language=RUST_LANGUAGE, methods=methods) for class_name, methods in methods_by_class.items()]

    def analyze(self) -> tuple[list[dict], list[dict]]:
        return _rows_from_text_classes(self.extract_classes())

    def _build_rust_method(self, qualified_class_name: str, function_node, name_node, params_node, body_node) -> TextMethod:
        method_simple_name = self._text(name_node)
        snippet = self._text(function_node)
        body_text = self._text(body_node)
        lines = [line for line in body_text.splitlines() if line.strip()]
        call_nodes = [node for node in _iter_nodes(body_node, "call_expression")]
        direct_calls = set()
        for call_node in call_nodes:
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue
            if function_node.type == "identifier":
                direct_calls.add(self._text(function_node))
            elif function_node.type == "field_expression":
                field = function_node.child_by_field_name("field")
                if field is not None:
                    direct_calls.add(self._text(field))
        instance_vars = {
            self._text(field_node)
            for node in _iter_nodes(body_node, "field_expression")
            if (value_node := node.child_by_field_name("value")) is not None
            and value_node.type == "self"
            and (field_node := node.child_by_field_name("field")) is not None
        }
        class_refs = {
            f"{self.relative_path}.{self._text(node)}"
            for node in _iter_nodes(body_node, "type_identifier")
            if self._text(node) in self.known_class_names
        }
        cc = 1 + sum(1 for node in _iter_nodes(body_node) if node.type in {"if_expression", "for_expression", "while_expression", "loop_expression", "match_expression"})
        cc += len(re.findall(r"&&|\|\|", body_text))
        parameters = sum(1 for child in params_node.named_children if child.type in {"parameter", "self_parameter"})
        if any(child.type == "self_parameter" for child in params_node.named_children):
            parameters -= 1
        return TextMethod(
            class_name=qualified_class_name,
            method_name=f"{qualified_class_name}.{method_simple_name}",
            method_simple_name=method_simple_name,
            language=RUST_LANGUAGE,
            body=snippet,
            loc=snippet.count("\n") + 1 if snippet else 1,
            lloc=len(lines) or 1,
            parameters=max(parameters, 0),
            fanout=len(call_nodes),
            cc=cc,
            instance_vars=instance_vars,
            direct_calls=direct_calls,
            class_refs=class_refs,
        )

    def _text(self, node) -> str:
        return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8")


class CSharpAnalyzer:
    def __init__(self, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.relative_path = relative_path
        self.source = source
        self.source_bytes = source.encode("utf-8")
        self.known_class_names = known_class_names
        self.parser = Parser(TREE_SITTER_LANGUAGES[CSHARP_LANGUAGE])

    def extract_classes(self) -> list[TextClass]:
        tree = self.parser.parse(self.source_bytes)
        root = tree.root_node
        if root.has_error:
            return []

        classes: list[TextClass] = []
        for class_node in _iter_nodes(root, "class_declaration"):
            name_node = class_node.child_by_field_name("name")
            body_node = class_node.child_by_field_name("body")
            if name_node is None or body_node is None:
                continue
            qualified_class_name = f"{self.relative_path}.{self._text(name_node)}"
            methods = []
            for method_node in _iter_nodes(body_node, "method_declaration"):
                method_name = method_node.child_by_field_name("name")
                params_node = method_node.child_by_field_name("parameters")
                block_node = method_node.child_by_field_name("body")
                if method_name is None or params_node is None or block_node is None:
                    continue
                methods.append(self._build_csharp_method(qualified_class_name, method_node, method_name, params_node, block_node))
            classes.append(TextClass(class_name=qualified_class_name, language=CSHARP_LANGUAGE, methods=methods))
        return classes

    def analyze(self) -> tuple[list[dict], list[dict]]:
        return _rows_from_text_classes(self.extract_classes())

    def _build_csharp_method(self, qualified_class_name: str, method_node, name_node, params_node, body_node) -> TextMethod:
        method_simple_name = self._text(name_node)
        snippet = self._text(method_node)
        body_text = self._text(body_node)
        lines = [line for line in body_text.splitlines() if line.strip()]
        call_nodes = [node for node in _iter_nodes(body_node, "invocation_expression")]
        direct_calls = set()
        for call_node in call_nodes:
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue
            if function_node.type == "identifier":
                direct_calls.add(self._text(function_node))
            elif function_node.type == "member_access_expression":
                name = function_node.child_by_field_name("name")
                if name is not None:
                    direct_calls.add(self._text(name))
        instance_vars = {
            self._text(name_node)
            for node in _iter_nodes(body_node, "member_access_expression")
            if (expr_node := node.child_by_field_name("expression")) is not None
            and expr_node.type == "this_expression"
            and (name_node := node.child_by_field_name("name")) is not None
        }
        class_refs = {
            f"{self.relative_path}.{self._text(node)}"
            for node in _iter_nodes(body_node, "identifier")
            if self._text(node) in self.known_class_names
        }
        cc = 1 + sum(1 for node in _iter_nodes(body_node) if node.type in {"if_statement", "for_statement", "foreach_statement", "while_statement", "do_statement", "switch_expression", "switch_statement", "catch_clause"})
        cc += len(re.findall(r"&&|\|\|", body_text))
        parameters = sum(1 for child in params_node.named_children if child.type == "parameter")
        return TextMethod(
            class_name=qualified_class_name,
            method_name=f"{qualified_class_name}.{method_simple_name}",
            method_simple_name=method_simple_name,
            language=CSHARP_LANGUAGE,
            body=snippet,
            loc=snippet.count("\n") + 1 if snippet else 1,
            lloc=len(lines) or 1,
            parameters=parameters,
            fanout=len(call_nodes),
            cc=cc,
            instance_vars=instance_vars,
            direct_calls=direct_calls,
            class_refs=class_refs,
        )

    def _text(self, node) -> str:
        return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8")


class TreeSitterAnalyzer:
    def __init__(self, language: str, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.language = language
        self.relative_path = relative_path
        self.source = source
        self.source_bytes = source.encode("utf-8")
        self.known_class_names = known_class_names
        self.parser = Parser(TREE_SITTER_LANGUAGES[language])

    def extract_classes(self) -> list[TextClass]:
        tree = self.parser.parse(self.source_bytes)
        root = tree.root_node
        if root.has_error:
            return []

        classes: list[TextClass] = []
        for class_node in _iter_nodes(root, "class_declaration"):
            name_node = class_node.child_by_field_name("name")
            body_node = class_node.child_by_field_name("body")
            if name_node is None or body_node is None:
                continue
            class_name = self._text(name_node)
            qualified = f"{self.relative_path}.{class_name}"
            methods: list[TextMethod] = []
            for child in body_node.named_children:
                child = self._unwrap_decorated_definition(child)
                if child.type == "method_definition":
                    method = self._build_method(qualified, child)
                elif child.type in {"field_definition", "public_field_definition"}:
                    method = self._build_field_arrow_method(qualified, child)
                else:
                    method = None
                if method is not None:
                    methods.append(method)
            classes.append(TextClass(class_name=qualified, language=self.language, methods=methods))
        return classes

    def analyze(self) -> tuple[list[dict], list[dict]]:
        return _rows_from_text_classes(self.extract_classes())

    def _build_method(self, qualified_class_name: str, method_node) -> TextMethod | None:
        name_node = method_node.child_by_field_name("name")
        params_node = method_node.child_by_field_name("parameters")
        body_node = method_node.child_by_field_name("body")
        if name_node is None or params_node is None or body_node is None:
            return None
        method_simple_name = self._text(name_node)
        snippet = self._text(method_node)
        body_text = self._text(body_node)
        lines = [line for line in body_text.splitlines() if line.strip()]
        call_nodes = [node for node in _iter_nodes(body_node, "call_expression")]
        direct_calls = set()
        for call_node in call_nodes:
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue
            if function_node.type in {"identifier", "property_identifier"}:
                direct_calls.add(self._text(function_node))
            elif function_node.type == "member_expression":
                property_node = function_node.child_by_field_name("property")
                if property_node is not None:
                    direct_calls.add(self._text(property_node))
        class_refs = {
            f"{self.relative_path}.{self._text(node)}"
            for node in _iter_nodes(body_node, "identifier")
            if self._text(node) in self.known_class_names
        }
        return TextMethod(
            class_name=qualified_class_name,
            method_name=f"{qualified_class_name}.{method_simple_name}",
            method_simple_name=method_simple_name,
            language=self.language,
            body=snippet,
            loc=snippet.count("\n") + 1 if snippet else 1,
            lloc=len(lines) or 1,
            parameters=self._parameter_count(params_node),
            fanout=len(call_nodes),
            cc=self._complexity(body_node, body_text),
            instance_vars={
                self._text(property_node)
                for node in _iter_nodes(body_node, "member_expression")
                if (object_node := node.child_by_field_name("object")) is not None
                and object_node.type == "this"
                and (property_node := node.child_by_field_name("property")) is not None
            },
            direct_calls=direct_calls,
            class_refs=class_refs,
        )

    def _build_field_arrow_method(self, qualified_class_name: str, field_node) -> TextMethod | None:
        name_node = field_node.child_by_field_name("property") or field_node.child_by_field_name("name")
        value_node = field_node.child_by_field_name("value")
        if name_node is None or value_node is None or value_node.type != "arrow_function":
            return None
        params_node = value_node.child_by_field_name("parameters")
        body_node = value_node.child_by_field_name("body")
        if params_node is None or body_node is None:
            return None
        method_simple_name = self._text(name_node)
        snippet = self._text(field_node)
        body_text = self._text(body_node)
        lines = [line for line in body_text.splitlines() if line.strip()]
        call_nodes = [node for node in _iter_nodes(body_node, "call_expression")]
        direct_calls = set()
        for call_node in call_nodes:
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue
            if function_node.type in {"identifier", "property_identifier"}:
                direct_calls.add(self._text(function_node))
            elif function_node.type == "member_expression":
                property_node = function_node.child_by_field_name("property")
                if property_node is not None:
                    direct_calls.add(self._text(property_node))
        class_refs = {
            f"{self.relative_path}.{self._text(node)}"
            for node in _iter_nodes(body_node, "identifier")
            if self._text(node) in self.known_class_names
        }
        return TextMethod(
            class_name=qualified_class_name,
            method_name=f"{qualified_class_name}.{method_simple_name}",
            method_simple_name=method_simple_name,
            language=self.language,
            body=snippet,
            loc=snippet.count("\n") + 1 if snippet else 1,
            lloc=len(lines) or 1,
            parameters=self._parameter_count(params_node),
            fanout=len(call_nodes),
            cc=self._complexity(body_node, body_text),
            instance_vars={
                self._text(property_node)
                for node in _iter_nodes(body_node, "member_expression")
                if (object_node := node.child_by_field_name("object")) is not None
                and object_node.type == "this"
                and (property_node := node.child_by_field_name("property")) is not None
            },
            direct_calls=direct_calls,
            class_refs=class_refs,
        )

    def _parameter_count(self, params_node) -> int:
        if self.language == TYPESCRIPT_LANGUAGE:
            return sum(1 for child in params_node.named_children if child.type in {"required_parameter", "optional_parameter", "rest_pattern"})
        return sum(1 for child in params_node.named_children if child.type == "identifier")

    def _complexity(self, body_node, body_text: str) -> int:
        branch_nodes = {
            "if_statement",
            "for_statement",
            "while_statement",
            "do_statement",
            "switch_case",
            "ternary_expression",
            "catch_clause",
        }
        cc = 1 + sum(1 for node in _iter_nodes(body_node) if node.type in branch_nodes)
        cc += len(re.findall(r"&&|\|\|", body_text))
        return cc

    def _text(self, node) -> str:
        return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8")

    def _unwrap_decorated_definition(self, node):
        if node.type != "decorated_definition":
            return node
        for child in node.named_children:
            if child.type != "decorator":
                return child
        return node


class CStyleAnalyzer:
    def __init__(self, language: str, relative_path: str, source: str, known_class_names: set[str]) -> None:
        self.language = language
        self.relative_path = relative_path
        self.source = source
        self.known_class_names = known_class_names

    def analyze(self) -> tuple[list[dict], list[dict]]:
        classes = self.extract_classes()
        if not classes:
            return [], []

        return _rows_from_text_classes(classes)

    def extract_classes(self) -> list[TextClass]:
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

def _run_java_helper(relative_path: str, source: str, known_class_names: set[str]) -> list[TextClass]:
    _ensure_java_helper_compiled()
    result = subprocess.run(
        [
            "java",
            "-cp",
            os.pathsep.join([str(JAVA_HELPER_BIN), str(JAVA_PARSER_JAR)]),
            JAVA_HELPER_MAIN,
            relative_path,
            _encode_known_text_classes(known_class_names, relative_path),
        ],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    return _decode_helper_classes(result.stdout)


def _ensure_java_helper_compiled() -> None:
    if not JAVA_PARSER_JAR.exists():
        java_lib_dir = JAVA_PARSER_JAR.parent
        java_lib_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "mvn",
                "dependency:copy",
                "-Dartifact=com.github.javaparser:javaparser-core:3.27.1",
                f"-DoutputDirectory={java_lib_dir}",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    class_file = JAVA_HELPER_BIN / f"{JAVA_HELPER_MAIN}.class"
    if class_file.exists() and class_file.stat().st_mtime >= JAVA_HELPER_SOURCE.stat().st_mtime:
        return
    JAVA_HELPER_BIN.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "javac",
            "-cp",
            str(JAVA_PARSER_JAR),
            "-d",
            str(JAVA_HELPER_BIN),
            str(JAVA_HELPER_SOURCE),
        ],
        text=True,
        capture_output=True,
        check=True,
    )


def _run_node_helper(language: str, relative_path: str, source: str, known_class_names: set[str]) -> list[TextClass]:
    result = subprocess.run(
        [
            "node",
            str(NODE_AST_HELPER),
            language,
            relative_path,
            _encode_known_text_classes(known_class_names, relative_path),
        ],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    return _decode_helper_classes(result.stdout)


def _decode_helper_classes(raw_output: str) -> list[TextClass]:
    if not raw_output.strip():
        return []
    payload = json.loads(raw_output)
    classes: list[TextClass] = []
    for class_payload in payload:
        methods = [
            TextMethod(
                class_name=method_payload["class_name"],
                method_name=method_payload["method_name"],
                method_simple_name=method_payload["method_simple_name"],
                language=method_payload["language"],
                body=method_payload["body"],
                loc=method_payload["loc"],
                lloc=method_payload["lloc"],
                parameters=method_payload["parameters"],
                fanout=method_payload["fanout"],
                cc=method_payload["cc"],
                instance_vars=set(method_payload["instance_vars"]),
                direct_calls=set(method_payload["direct_calls"]),
                class_refs=set(method_payload["class_refs"]),
            )
            for method_payload in class_payload["methods"]
        ]
        classes.append(
            TextClass(
                class_name=class_payload["class_name"],
                language=class_payload["language"],
                methods=methods,
            )
        )
    return classes


def _encode_known_text_classes(known_class_names: set[str], relative_path: str) -> str:
    entries: dict[str, set[str]] = defaultdict(set)
    for qualified_name in known_class_names:
        class_name = qualified_name.rsplit(".", maxsplit=1)[-1]
        entries[class_name].add(qualified_name)
    return ARG_SEPARATOR.join(
        f"{class_name}{CLASS_NAME_SEPARATOR}{CLASS_LIST_SEPARATOR.join(sorted(qualified_names))}"
        for class_name, qualified_names in sorted(entries.items())
    )


def _build_python_project_index(python_trees: dict[str, ast.AST]) -> PythonProjectIndex:
    import_to_relative: dict[str, str] = {}
    for relative in python_trees:
        module_import = _python_relative_to_import_path(relative)
        if module_import:
            import_to_relative[module_import] = relative

    class_infos: dict[str, PythonClassInfo] = {}
    classes_by_simple: dict[str, list[str]] = defaultdict(list)
    classes_by_module: dict[str, dict[str, str]] = defaultdict(dict)

    for module_name, tree in python_trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            qualified_name = f"{module_name}.{node.name}"
            methods = {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            class_infos[qualified_name] = PythonClassInfo(
                qualified_name=qualified_name,
                module_name=module_name,
                class_name=node.name,
                methods=methods,
                base_classes=set(),
                method_return_types={},
            )
            classes_by_simple[node.name].append(qualified_name)
            classes_by_module[module_name][node.name] = qualified_name

    module_infos: dict[str, PythonModuleInfo] = {}
    for module_name, tree in python_trees.items():
        imported_modules: dict[str, str] = {}
        imported_classes: dict[str, str] = {}
        function_return_types: dict[str, str] = {}
        for node in tree.body if isinstance(tree, ast.Module) else []:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_module = import_to_relative.get(alias.name)
                    if imported_module:
                        imported_modules[alias.asname or alias.name.split(".")[-1]] = imported_module
            elif isinstance(node, ast.ImportFrom):
                base_import = _python_resolve_import_from(module_name, node.module, node.level)
                if not base_import:
                    continue
                base_module = import_to_relative.get(base_import)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if base_module and alias.name in classes_by_module.get(base_module, {}):
                        imported_classes[alias.asname or alias.name] = classes_by_module[base_module][alias.name]
                        continue
                    submodule_import = f"{base_import}.{alias.name}"
                    submodule = import_to_relative.get(submodule_import)
                    if submodule:
                        imported_modules[alias.asname or alias.name] = submodule
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return_type = _resolve_python_class_expression(
                    node.returns,
                    module_name,
                    PythonModuleInfo(imported_modules=imported_modules, imported_classes=imported_classes, function_return_types={}),
                    classes_by_module,
                    classes_by_simple,
                )
                if return_type:
                    function_return_types[node.name] = return_type
        module_infos[module_name] = PythonModuleInfo(
            imported_modules=imported_modules,
            imported_classes=imported_classes,
            function_return_types=function_return_types,
        )

    for class_info in class_infos.values():
        class_node = _find_python_class_node(python_trees[class_info.module_name], class_info.class_name)
        if class_node is None:
            continue
        module_info = module_infos.get(class_info.module_name, PythonModuleInfo({}, {}, {}))
        for base in class_node.bases:
            resolved = _resolve_python_class_expression(base, class_info.module_name, module_info, classes_by_module, classes_by_simple)
            if resolved:
                class_info.base_classes.add(resolved)
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                resolved_return = _resolve_python_class_expression(
                    item.returns,
                    class_info.module_name,
                    module_info,
                    classes_by_module,
                    classes_by_simple,
                )
                if resolved_return:
                    class_info.method_return_types[item.name] = resolved_return

    return PythonProjectIndex(
        module_infos=module_infos,
        class_infos=class_infos,
        classes_by_simple=dict(classes_by_simple),
        classes_by_module=dict(classes_by_module),
    )


def _find_python_class_node(tree: ast.AST, class_name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _python_relative_to_import_path(relative: str) -> str:
    path = Path(relative)
    if path.name == "__init__.py":
        return ".".join(path.parent.parts)
    if path.suffix == ".py":
        return ".".join(path.with_suffix("").parts)
    return ""


def _python_resolve_import_from(module_name: str, imported_module: str | None, level: int) -> str:
    current_parts = Path(module_name).with_suffix("").parts
    if current_parts and current_parts[-1] == "__init__":
        current_parts = current_parts[:-1]
    if level:
        keep = max(len(current_parts) - level, 0)
        base_parts = list(current_parts[:keep])
    else:
        base_parts = list(current_parts[:-1])
    imported_parts = imported_module.split(".") if imported_module else []
    parts = [part for part in [*base_parts, *imported_parts] if part]
    return ".".join(parts)


def _resolve_python_class_expression(
    node: ast.AST,
    module_name: str,
    module_info: PythonModuleInfo,
    classes_by_module: dict[str, dict[str, str]],
    classes_by_simple: dict[str, list[str]],
) -> str | None:
    if isinstance(node, ast.Name):
        if node.id in module_info.imported_classes:
            return module_info.imported_classes[node.id]
        module_class = classes_by_module.get(module_name, {}).get(node.id)
        if module_class:
            return module_class
        candidates = classes_by_simple.get(node.id, [])
        if len(candidates) == 1:
            return candidates[0]
        return None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        imported_module = module_info.imported_modules.get(node.value.id)
        if imported_module:
            return classes_by_module.get(imported_module, {}).get(node.attr)
    if isinstance(node, ast.Subscript):
        return _resolve_python_class_expression(node.value, module_name, module_info, classes_by_module, classes_by_simple)
    return None


def analyze_repository_snapshot(repo_root: Path, commit_hash: str, repo_name: str, branch: str, commit_date: str) -> AnalysisResult:
    python_trees: dict[str, ast.AST] = {}
    text_sources: dict[str, tuple[str, str]] = {}
    file_metrics: list[dict] = []
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
        elif language == JAVA_LANGUAGE:
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text_sources[relative] = (language, source)
            for class_name in re.findall(r"\bclass\s+([A-Za-z_]\w*)", source):
                known_text_class_names.add(f"{relative}.{class_name}")
        elif language in SUPPORTED_C_STYLE_LANGUAGES:
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text_sources[relative] = (language, source)
            if language in {JAVASCRIPT_LANGUAGE, TYPESCRIPT_LANGUAGE, CSHARP_LANGUAGE}:
                for class_name in re.findall(r"\bclass\s+([A-Za-z_]\w*)", source):
                    known_text_class_names.add(f"{relative}.{class_name}")
            elif language == GO_LANGUAGE:
                for class_name in re.findall(r"\btype\s+([A-Za-z_]\w*)\s+struct\b", source):
                    known_text_class_names.add(f"{relative}.{class_name}")
            elif language == RUST_LANGUAGE:
                for class_name in re.findall(r"\bstruct\s+([A-Za-z_]\w*)\b", source):
                    known_text_class_names.add(f"{relative}.{class_name}")

    class_rows: list[dict] = []
    method_rows: list[dict] = []
    python_project_index = _build_python_project_index(python_trees)
    python_method_fanin_sources: dict[str, set[str]] = defaultdict(set)
    python_class_fanin_sources: dict[str, set[str]] = defaultdict(set)
    python_class_rows: list[dict] = []
    python_method_rows: list[dict] = []
    for module_name, tree in python_trees.items():
        analyzer = PythonAnalyzer(
            module_name=module_name,
            project_index=python_project_index,
            method_fanin_sources=python_method_fanin_sources,
            class_fanin_sources=python_class_fanin_sources,
        )
        module_classes, module_methods = analyzer.analyze(tree)
        python_class_rows.extend(module_classes)
        python_method_rows.extend(module_methods)
    for row in python_class_rows:
        row["fanin"] = len(python_class_fanin_sources.get(row["class_name"], set()))
    for row in python_method_rows:
        row["fanin"] = len(python_method_fanin_sources.get(row["method_name"], set()))
    class_rows.extend(_annotate_rows(python_class_rows, repo_name, branch, commit_hash, commit_date))
    method_rows.extend(_annotate_rows(python_method_rows, repo_name, branch, commit_hash, commit_date))
    text_classes: list[TextClass] = []
    for relative, (language, source) in text_sources.items():
        analyzer = (
            JavaAnalyzer(relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == JAVA_LANGUAGE
            else JavaScriptAnalyzer(language=language, relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == JAVASCRIPT_LANGUAGE
            else TypeScriptAnalyzer(language=language, relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == TYPESCRIPT_LANGUAGE
            else GoAnalyzer(relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == GO_LANGUAGE
            else RustAnalyzer(relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == RUST_LANGUAGE
            else CSharpAnalyzer(relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language == CSHARP_LANGUAGE
            else TreeSitterAnalyzer(language=language, relative_path=relative, source=source, known_class_names=known_text_class_names)
            if language in TREE_SITTER_LANGUAGES
            else CStyleAnalyzer(language=language, relative_path=relative, source=source, known_class_names=known_text_class_names)
        )
        text_classes.extend(analyzer.extract_classes())
    text_class_rows, text_method_rows = _rows_from_text_classes(text_classes)
    class_rows.extend(_annotate_rows(text_class_rows, repo_name, branch, commit_hash, commit_date))
    method_rows.extend(_annotate_rows(text_method_rows, repo_name, branch, commit_hash, commit_date))

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
        "total_loc": sum(row["loc"] for row in file_metrics),
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


def _iter_nodes(node, node_type: str | None = None):
    stack = [node]
    while stack:
        current = stack.pop()
        if node_type is None or current.type == node_type:
            yield current
        stack.extend(reversed(current.named_children))
