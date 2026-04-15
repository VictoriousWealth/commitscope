from commitscope.aws.runtime import load_stepfunctions_input
import json


def test_dispatch_payload_contains_config_json() -> None:
    payload = load_stepfunctions_input("examples/config.dev.json")
    assert payload["execution_mode"] == "stepfunctions"
    assert payload["project"] == "commitscope"
    assert payload["environment"] == "dev"
    assert "config_json" in payload
    assert payload["branch"] == "main"
    config_json = json.loads(payload["config_json"])
    assert config_json["runtime"]["execution_mode"] == "stepfunctions"
    assert config_json["storage"]["write_local_json"] is False
    assert config_json["storage"]["write_local_csv"] is False
    assert config_json["storage"]["write_local_parquet"] is True
    assert config_json["storage"]["write_s3"] is True
