from __future__ import annotations

import json
import os

from commitscope.config import load_config
from commitscope.pipeline.run import run_pipeline


def main() -> None:
    config_path = os.environ.get("COMMITSCOPE_CONFIG", "/app/examples/config.dev.json")
    outputs = run_pipeline(load_config(config_path))
    print(json.dumps({name: str(path) for name, path in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
