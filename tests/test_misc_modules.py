import json
from dataclasses import asdict
from pathlib import Path

from commitscope.analysis.languages import language_for_file
from commitscope.aws import container as container_module
from commitscope.aws.runtime import build_stepfunctions_input
from commitscope.config import load_config
from commitscope.utils.fs import ensure_dir


def test_language_for_file_maps_known_suffixes_and_other() -> None:
    assert language_for_file("src/example.py") == "python"
    assert language_for_file("ui/component.tsx") == "typescript"
    assert language_for_file("assets/style.scss") == "scss"
    assert language_for_file("notes.unknown") == "other"


def test_ensure_dir_creates_and_returns_directory(tmp_path) -> None:
    target = tmp_path / "nested" / "path"

    returned = ensure_dir(target)

    assert returned == target
    assert target.is_dir()


def test_build_stepfunctions_input_serializes_config() -> None:
    config = load_config("examples/config.dev.json")

    payload = build_stepfunctions_input(config)

    assert payload["execution_mode"] == "stepfunctions"
    assert payload["repo_url"] == config.repo.url
    assert json.loads(payload["config_json"]) == asdict(config)


def test_container_main_prints_pipeline_outputs(monkeypatch, capsys) -> None:
    config = load_config("examples/config.dev.json")
    monkeypatch.setattr("commitscope.aws.container.load_config_from_env", lambda default: config)
    monkeypatch.setattr("commitscope.aws.container.run_pipeline", lambda loaded: {"summary": Path("/tmp/summary.md")})

    container_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"summary": "/tmp/summary.md"}
