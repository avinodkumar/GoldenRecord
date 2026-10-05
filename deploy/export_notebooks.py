"""Convert fabric/notebooks/*.py (# %% cells) into Fabric item folders that `fab import` accepts.

Output: build/fabric/<name>.Notebook/{notebook-content.py, .platform}
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "fabric" / "notebooks"
OUT = ROOT / "build" / "fabric"

HEADER = """# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   }
# META }
"""
CELL = "\n# CELL ********************\n\n"


def convert(path: Path) -> Path:
    text = path.read_text(encoding="utf-8")
    cells = [c.strip("\n") for c in re.split(r"^# %%.*$", text, flags=re.M)]
    cells = [c for c in cells if c.strip()]
    target = OUT / f"{path.stem}.Notebook"
    target.mkdir(parents=True, exist_ok=True)
    (target / "notebook-content.py").write_text(HEADER + "".join(CELL + c + "\n" for c in cells), encoding="utf-8")
    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Notebook", "displayName": path.stem},
        "config": {"version": "2.0", "logicalId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"goldenrecord/{path.stem}"))},
    }
    (target / ".platform").write_text(json.dumps(platform, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    for nb in sorted(SRC.glob("nb_*.py")):
        print(convert(nb))
    sys.exit(0)
