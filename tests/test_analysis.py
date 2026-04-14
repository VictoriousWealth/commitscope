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


def test_python_cross_module_constructor_and_method_resolution_updates_fanin_and_cbo() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        package = repo_root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "service.py").write_text(
            "class Service:\n"
            "    def run(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        (package / "controller.py").write_text(
            "from pkg.service import Service\n"
            "class Controller:\n"
            "    def __init__(self):\n"
            "        self.service = Service()\n"
            "    def work(self):\n"
            "        return self.service.run()\n",
            encoding="utf-8",
        )

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        service_class = next(row for row in result.class_metrics if row["class_name"] == "pkg/service.py.Service")
        controller_class = next(row for row in result.class_metrics if row["class_name"] == "pkg/controller.py.Controller")
        service_run = next(row for row in result.method_metrics if row["method_name"] == "pkg/service.py.Service.run")

        assert service_class["fanin"] == 1
        assert controller_class["cbo"] == 1
        assert service_run["fanin"] == 1


def test_python_module_alias_resolution_tracks_cross_module_calls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        package = repo_root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "service.py").write_text(
            "class Service:\n"
            "    def ping(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        (package / "consumer.py").write_text(
            "import pkg.service as service_mod\n"
            "class Consumer:\n"
            "    def use(self):\n"
            "        svc = service_mod.Service()\n"
            "        return svc.ping()\n",
            encoding="utf-8",
        )

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        service_ping = next(row for row in result.method_metrics if row["method_name"] == "pkg/service.py.Service.ping")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "pkg/consumer.py.Consumer")

        assert service_ping["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_python_parameter_annotation_resolution_tracks_method_calls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        package = repo_root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "service.py").write_text(
            "class Service:\n"
            "    def run(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        (package / "consumer.py").write_text(
            "from pkg.service import Service\n"
            "class Consumer:\n"
            "    def use(self, service: Service):\n"
            "        return service.run()\n",
            encoding="utf-8",
        )

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        service_run = next(row for row in result.method_metrics if row["method_name"] == "pkg/service.py.Service.run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "pkg/consumer.py.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_python_inherited_method_resolution_counts_base_method_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        package = repo_root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "base.py").write_text(
            "class Base:\n"
            "    def run(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        (package / "child.py").write_text(
            "from pkg.base import Base\n"
            "class Child(Base):\n"
            "    def use(self):\n"
            "        return self.run()\n",
            encoding="utf-8",
        )

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        base_run = next(row for row in result.method_metrics if row["method_name"] == "pkg/base.py.Base.run")
        child_class = next(row for row in result.class_metrics if row["class_name"] == "pkg/child.py.Child")

        assert base_run["fanin"] == 1
        assert child_class["cbo"] == 1


def test_python_return_annotation_resolution_supports_chained_calls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        package = repo_root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "service.py").write_text(
            "class Service:\n"
            "    def run(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        (package / "controller.py").write_text(
            "from pkg.service import Service\n"
            "class Controller:\n"
            "    def make_service(self) -> Service:\n"
            "        return Service()\n"
            "    def work(self):\n"
            "        return self.make_service().run()\n",
            encoding="utf-8",
        )

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        service_run = next(row for row in result.method_metrics if row["method_name"] == "pkg/service.py.Service.run")
        controller_class = next(row for row in result.class_metrics if row["class_name"] == "pkg/controller.py.Controller")

        assert service_run["fanin"] == 1
        assert controller_class["cbo"] == 1


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


def test_javascript_class_field_arrow_function_is_treated_as_method() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.js").write_text(
            "class Sample {\n"
            "  first = (value) => {\n"
            "    if (value) {\n"
            "      return helper();\n"
            "    }\n"
            "    return this.value;\n"
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
        assert any(row["method_name"] == "sample.js.Sample.first" for row in result.method_metrics)


def test_non_python_fanin_does_not_match_multiple_same_named_methods() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "first.js").write_text(
            "class First {\n"
            "  run() {\n"
            "    return 1;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "second.js").write_text(
            "class Second {\n"
            "  run() {\n"
            "    return 2;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "caller.js").write_text(
            "class Caller {\n"
            "  work() {\n"
            "    return run();\n"
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

        first_run = next(row for row in result.method_metrics if row["method_name"] == "first.js.First.run")
        second_run = next(row for row in result.method_metrics if row["method_name"] == "second.js.Second.run")

        assert first_run["fanin"] == 0
        assert second_run["fanin"] == 0


def test_commit_summary_total_loc_uses_file_totals() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.py").write_text(
            "import os\n"
            "\n"
            "class Sample:\n"
            "    def run(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )

        result = analyze_repository_snapshot(
            repo_root=repo_root,
            commit_hash="abc123",
            repo_name="repo",
            branch="main",
            commit_date="2026-03-21",
        )

        assert result.commit_summary["total_loc"] == 5


def test_javascript_cross_file_constructor_and_method_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "service.js").write_text(
            "export class Service {\n"
            "  run() {\n"
            "    return 1;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "consumer.js").write_text(
            "import { Service } from './service';\n"
            "class Consumer {\n"
            "  work() {\n"
            "    const service = new Service();\n"
            "    return service.run();\n"
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

        service_run = next(row for row in result.method_metrics if row["method_name"] == "service.js.Service.run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "consumer.js.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_typescript_cross_file_import_alias_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "service.ts").write_text(
            "export class Service {\n"
            "  run(): number {\n"
            "    return 1;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "consumer.ts").write_text(
            "import { Service as RepoService } from './service';\n"
            "class Consumer {\n"
            "  work(): number {\n"
            "    const service: RepoService = new RepoService();\n"
            "    return service.run();\n"
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

        service_run = next(row for row in result.method_metrics if row["method_name"] == "service.ts.Service.run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "consumer.ts.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_java_cross_file_constructor_and_method_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Service.java").write_text(
            "public class Service {\n"
            "    public int run() {\n"
            "        return 1;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "Consumer.java").write_text(
            "public class Consumer {\n"
            "    public int work() {\n"
            "        Service service = new Service();\n"
            "        return service.run();\n"
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

        service_run = next(row for row in result.method_metrics if row["method_name"] == "Service.java.Service.run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "Consumer.java.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_java_static_import_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Helpers.java").write_text(
            "public class Helpers {\n"
            "    public static int ping() {\n"
            "        return 1;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "Consumer.java").write_text(
            "import static Helpers.ping;\n"
            "public class Consumer {\n"
            "    public int work() {\n"
            "        return ping();\n"
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

        helper_ping = next(row for row in result.method_metrics if row["method_name"] == "Helpers.java.Helpers.ping")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "Consumer.java.Consumer")

        assert helper_ping["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_go_cross_file_receiver_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "service.go").write_text(
            "package sample\n"
            "type Service struct {}\n"
            "func (s *Service) Run() int {\n"
            "    return 1\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "consumer.go").write_text(
            "package sample\n"
            "type Consumer struct {}\n"
            "func (c *Consumer) Work() int {\n"
            "    svc := &Service{}\n"
            "    return svc.Run()\n"
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

        service_run = next(row for row in result.method_metrics if row["method_name"] == "service.go.Service.Run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "consumer.go.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_rust_cross_file_receiver_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "service.rs").write_text(
            "struct Service;\n"
            "impl Service {\n"
            "    fn new() -> Self { Self }\n"
            "    fn run(&self) -> i32 { 1 }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "consumer.rs").write_text(
            "struct Consumer;\n"
            "impl Consumer {\n"
            "    fn work(&self) -> i32 {\n"
            "        let service = Service::new();\n"
            "        service.run()\n"
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

        service_run = next(row for row in result.method_metrics if row["method_name"] == "service.rs.Service.run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "consumer.rs.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


def test_csharp_cross_file_receiver_resolution_updates_fanin() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Service.cs").write_text(
            "public class Service {\n"
            "    public int Run() {\n"
            "        return 1;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_root / "Consumer.cs").write_text(
            "public class Consumer {\n"
            "    public int Work() {\n"
            "        var service = new Service();\n"
            "        return service.Run();\n"
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

        service_run = next(row for row in result.method_metrics if row["method_name"] == "Service.cs.Service.Run")
        consumer_class = next(row for row in result.class_metrics if row["class_name"] == "Consumer.cs.Consumer")

        assert service_run["fanin"] == 1
        assert consumer_class["cbo"] == 1


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


def test_go_metrics_are_generated_for_struct_methods() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.go").write_text(
            "package sample\n"
            "type Counter struct {\n"
            "    value int\n"
            "}\n"
            "func (c *Counter) Inc(step int) int {\n"
            "    if step > 0 {\n"
            "        c.value += step\n"
            "    }\n"
            "    return c.value\n"
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
        assert any(row["class_name"] == "sample.go.Counter" for row in result.class_metrics)
        method_row = next(row for row in result.method_metrics if row["method_name"] == "sample.go.Counter.Inc")
        assert method_row["language"] == "go"
        assert method_row["parameters"] == 1
        assert method_row["cc"] >= 2


def test_rust_metrics_are_generated_for_impl_methods() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.rs").write_text(
            "struct Counter {\n"
            "    value: i32,\n"
            "}\n"
            "impl Counter {\n"
            "    fn inc(&self, step: i32) -> i32 {\n"
            "        if step > 0 {\n"
            "            return self.value + step;\n"
            "        }\n"
            "        self.value\n"
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
        assert any(row["class_name"] == "sample.rs.Counter" for row in result.class_metrics)
        method_row = next(row for row in result.method_metrics if row["method_name"] == "sample.rs.Counter.inc")
        assert method_row["language"] == "rust"
        assert method_row["parameters"] == 1
        assert method_row["cc"] >= 2


def test_csharp_metrics_are_generated_for_simple_class() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Sample.cs").write_text(
            "public class Sample {\n"
            "    private int _value;\n"
            "    public int Read(int step) {\n"
            "        if (step > 0) {\n"
            "            return this._value + step;\n"
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
        assert any(row["class_name"] == "Sample.cs.Sample" for row in result.class_metrics)
        method_row = next(row for row in result.method_metrics if row["method_name"] == "Sample.cs.Sample.Read")
        assert method_row["language"] == "csharp"
        assert method_row["parameters"] == 1
        assert method_row["cc"] >= 2


def test_typescript_public_field_arrow_function_is_treated_as_method() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.ts").write_text(
            "class Sample {\n"
            "  first = (value: number): number => {\n"
            "    if (value > 0) {\n"
            "      return helper();\n"
            "    }\n"
            "    return this.value;\n"
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
        method_row = next(row for row in result.method_metrics if row["method_name"] == "sample.ts.Sample.first")
        assert method_row["parameters"] == 1
        assert method_row["language"] == "typescript"


def test_typescript_decorated_method_is_treated_as_method() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.ts").write_text(
            "function bound(target: unknown, key: string, descriptor: PropertyDescriptor) {\n"
            "  return descriptor;\n"
            "}\n"
            "class Sample {\n"
            "  @bound\n"
            "  first(value: number): number {\n"
            "    if (value > 0 && this.ready) {\n"
            "      return helper(value);\n"
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
        method_row = next(row for row in result.method_metrics if row["method_name"] == "sample.ts.Sample.first")
        assert method_row["parameters"] == 1
        assert method_row["cc"] >= 3


def test_typescript_decorated_field_arrow_function_is_treated_as_method() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.ts").write_text(
            "function bound(target: unknown, key: string, descriptor?: PropertyDescriptor) {\n"
            "  return descriptor;\n"
            "}\n"
            "class Sample {\n"
            "  @bound\n"
            "  first = (value: number): number => {\n"
            "    if (value > 0 || this.ready) {\n"
            "      return helper(value);\n"
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
        method_row = next(row for row in result.method_metrics if row["method_name"] == "sample.ts.Sample.first")
        assert method_row["fanin"] == 0
        assert method_row["cc"] >= 3


def test_javascript_private_method_is_treated_as_method() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "sample.js").write_text(
            "class Sample {\n"
            "  #secret(value) {\n"
            "    if (value) {\n"
            "      return helper();\n"
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
        assert any(row["method_name"] == "sample.js.Sample.#secret" for row in result.method_metrics)


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


def test_java_analysis_handles_nested_classes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory)
        (repo_root / "Outer.java").write_text(
            "public class Outer {\n"
            "    public int top() {\n"
            "        return 1;\n"
            "    }\n"
            "    static class Inner {\n"
            "        public int nested() {\n"
            "            if (true) {\n"
            "                return 2;\n"
            "            }\n"
            "            return 0;\n"
            "        }\n"
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

        class_names = {row["class_name"] for row in result.class_metrics}
        method_names = {row["method_name"] for row in result.method_metrics}
        assert "Outer.java.Outer" in class_names
        assert "Outer.java.Inner" in class_names
        assert "Outer.java.Outer.top" in method_names
        assert "Outer.java.Inner.nested" in method_names


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

        file_loc_total = sum(row["loc"] for row in result.file_metrics)
        assert result.commit_summary["total_loc"] == file_loc_total


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
