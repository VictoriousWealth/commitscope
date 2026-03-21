from commitscope.aws.runtime import load_stepfunctions_input


def test_dispatch_payload_contains_config_json() -> None:
    payload = load_stepfunctions_input("examples/config.dev.json")
    assert payload["execution_mode"] == "stepfunctions"
    assert "config_json" in payload
    assert payload["branch"] == "main"
