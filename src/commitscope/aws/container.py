from __future__ import annotations

import json
import os

from commitscope.config import load_config_from_env
from commitscope.pipeline.run import run_pipeline


def main() -> None:
    config = load_config_from_env(os.environ.get("COMMITSCOPE_CONFIG", "/app/examples/config.dev.json"))
    outputs = run_pipeline(config)
    print(json.dumps({name: str(path) for name, path in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
