"""Render the ablation results (data/ablation/ablation.json, written by `python -m goldenrecord ablation`) as a terminal frame."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from capture import OUT, terminal_frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
d = json.loads((ROOT / "data" / "ablation" / "ablation.json").read_text(encoding="utf-8"))
rows = d["rows"]
fmt = lambda v, pct=False: "–" if v is None else (f"{v:.1%}" if pct else (f"{v:,.0f}" if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 10 else str(v)))
metrics = [("Bad rows with a per-row reason", "per_record_reasons", False),
           ("Records repaired (with lineage)", "records_repaired", False),
           ("Duplicate vendors merged (of 1,743)", "duplicate_vendors_merged", False),
           ("Vendors resolved exactly (of 3,000)", "vendors_resolved_exactly", False),
           ("Match recall", "pair_recall", False),
           ("Gold spend on the correct vendor", "gold_spend_on_correct_vendor", True),
           ("Steward decisions", "steward_decisions", False),
           ("LLM calls per run", "llm_calls", False),
           ("Same output on rerun", "deterministic", False)]
heads = ["Native MLV only", "Rules only", "+ steward patterns", "LLM every row"]
out = [d["meta"]["dataset"], "", f"{'':38}" + "".join(f"{h:>20}" for h in heads), "-" * 118]
for label, key, pct in metrics:
    out.append(f"{label:38}" + "".join(f"{fmt(r[key], pct):>20}" for r in rows))
out += ["", "Note: " + d["meta"]["note"]]
with sync_playwright() as p:
    b = p.chromium.launch()
    terminal_frame(b, "61_ablation", "Measured comparison · same seeded dataset", "python -m goldenrecord ablation",
                   "\n".join(out), max_lines=40)
    b.close()
