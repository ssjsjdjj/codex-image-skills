"""Run the bundled processor with this account's private environment and CPU model."""
import json
import importlib.util
import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "runtime.json").read_text(encoding="utf-8-sig"))
    expected_python = Path(config["python"]).resolve()
    if Path(sys.executable).resolve() != expected_python:
        raise RuntimeError("请使用本技能 run_bg.ps1 或 runtime.json 指定的专用 Python")
    model_dir = Path(config["model_dir"])
    cache_dir = Path(config["cache_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(model_dir)
    os.environ["NUMBA_CACHE_DIR"] = str(cache_dir / "numba")
    os.environ["OMP_NUM_THREADS"] = str(config.get("cpu_threads", 2))
    os.environ["PYTHONIOENCODING"] = "utf-8"
    # The engine creates its local CPU session only when cutout actually needs it.
    # Help, planning, alpha inputs, queue and idle do not import rembg/numba.
    processor = root / "scripts/bg_assets.py"
    spec = importlib.util.spec_from_file_location("chutu_bg_processor", processor)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)

    sys.argv[0] = str(processor)
    engine.main()


if __name__ == "__main__":
    main()
