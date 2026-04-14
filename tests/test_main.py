import json
from pathlib import Path

from commitscope import main as main_module
from commitscope.config import load_config


def test_load_local_tables_reads_known_csvs(tmp_path) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path)
    processed = tmp_path / "processed"
    (processed / "commit_summary").mkdir(parents=True)
    (processed / "class_metrics").mkdir(parents=True)
    (processed / "commit_summary" / "commit_summary.csv").write_text(
        "commit_hash,commit_date,total_classes\nabc123,2026-03-22,1\n",
        encoding="utf-8",
    )
    (processed / "class_metrics" / "class_metrics.csv").write_text(
        "class_name,wmc\nExample,5\n",
        encoding="utf-8",
    )

    tables = main_module._load_local_tables(config)

    assert tables["commit_summary"][0]["commit_hash"] == "abc123"
    assert tables["class_metrics"][0]["class_name"] == "Example"


def test_load_local_tables_falls_back_to_json_and_parquet(tmp_path) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path)
    processed = tmp_path / "processed"
    (processed / "commit_summary").mkdir(parents=True)
    (processed / "class_metrics" / "repo=repo" / "branch=main" / "commit_hash=abc123" / "commit_date=2026-03-22").mkdir(parents=True)
    (processed / "commit_summary" / "commit_summary.json").write_text(
        '[{"commit_hash":"abc123","commit_date":"2026-03-22","total_classes":1}]',
        encoding="utf-8",
    )

    import pandas as pd

    pd.DataFrame([{"class_name": "Example", "wmc": 5}]).to_parquet(
        processed / "class_metrics" / "repo=repo" / "branch=main" / "commit_hash=abc123" / "commit_date=2026-03-22" / "data.parquet",
        index=False,
    )

    tables = main_module._load_local_tables(config)

    assert tables["commit_summary"][0]["commit_hash"] == "abc123"
    assert tables["class_metrics"][0]["class_name"] == "Example"


def test_main_run_command_prints_pipeline_outputs(monkeypatch, capsys) -> None:
    config = load_config("examples/config.dev.json")
    monkeypatch.setattr("sys.argv", ["commitscope", "run", "--config", "examples/config.dev.json"])
    monkeypatch.setattr("commitscope.main.load_config", lambda path: config)
    monkeypatch.setattr("commitscope.main.run_pipeline", lambda loaded: {"summary": Path("/tmp/summary.md")})

    main_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"summary": "/tmp/summary.md"}


def test_main_dispatch_command_prints_stepfunctions_payload(monkeypatch, capsys) -> None:
    config = load_config("examples/config.dev.json")
    monkeypatch.setattr("sys.argv", ["commitscope", "dispatch", "--config", "examples/config.dev.json"])
    monkeypatch.setattr("commitscope.main.load_config", lambda path: config)
    monkeypatch.setattr("commitscope.main.load_stepfunctions_input", lambda path: {"execution_mode": "stepfunctions"})

    main_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"execution_mode": "stepfunctions"}


def test_main_report_command_writes_manifest(monkeypatch, capsys, tmp_path) -> None:
    config = load_config("examples/config.dev.json")
    config.reporting.output_root = str(tmp_path)
    monkeypatch.setattr("sys.argv", ["commitscope", "report", "--config", "examples/config.dev.json"])
    monkeypatch.setattr("commitscope.main.load_config", lambda path: config)
    monkeypatch.setattr("commitscope.main._load_local_tables", lambda loaded: {"commit_summary": [], "class_metrics": []})
    monkeypatch.setattr(
        "commitscope.main.write_reporting_artifacts",
        lambda loaded, tables: {"summary": Path("/tmp/summary.md")},
    )
    monkeypatch.setattr(
        "commitscope.main.write_runtime_manifest",
        lambda loaded, outputs: Path("/tmp/runtime_manifest.json"),
    )

    main_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"summary": "/tmp/summary.md", "runtime_manifest": "/tmp/runtime_manifest.json"}
