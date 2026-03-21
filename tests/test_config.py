from commitscope.config import load_config


def test_load_config_reads_nested_sections() -> None:
    config = load_config("examples/config.dev.json")
    assert config.project == "commitscope"
    assert config.aws_region == "eu-west-2"
    assert config.storage.prefixes.processed == "processed"
