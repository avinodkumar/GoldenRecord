"""Capture real frames from the running dev harness for the pitch video.

Drives the live system (agent API + steward UI at localhost) through the demo story and saves
1920x1080 PNGs into video/out/frames. Nothing is mocked: every frame is the UI after a real API action.
Also renders terminal output (pytest, ablation) and Fabric notebook code as frames.

Run with the harness up:  python video/capture.py
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video" / "out" / "frames"
API = "http://localhost:8000"
UI = "http://localhost:8501"
W, H = 1920, 1080


def call(method: str, path: str, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def docker_py(code: str) -> str:
    return subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=600).stdout


class Shooter:
    def __init__(self, page):
        self.page = page

    def goto(self, view: str):
        self.page.goto(UI, wait_until="networkidle")
        self.page.wait_for_selector("text=GoldenRecord", timeout=60000)
        self.page.get_by_text(view, exact=True).first.click()
        self.settle()

    def settle(self, extra: float = 2.5):
        try:
            self.page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')",
                                        timeout=60000)
        except Exception:
            pass
        time.sleep(extra)

    def shot(self, name: str, scroll_to: str | None = None):
        if scroll_to:
            self.page.get_by_text(scroll_to).first.scroll_into_view_if_needed()
            time.sleep(0.8)
        self.page.screenshot(path=str(OUT / f"{name}.png"))
        print("frame", name)


TERM_CSS = """body{margin:0;background:#0F1B2D;width:1920px;height:1080px;font-family:'Cascadia Mono',Consolas,monospace;}
.bar{height:56px;background:#1A2A40;display:flex;align-items:center;padding:0 28px;gap:12px;color:#9AA7B8;font:600 20px 'Segoe UI';}
.dot{width:16px;height:16px;border-radius:50%;}
pre{margin:0;padding:28px 40px;color:#E6EDF3;font-size:21px;line-height:1.45;white-space:pre-wrap;}
.p{color:#E8B84A}.ok{color:#7EE787}"""


def terminal_frame(browser, name: str, title: str, command: str, output: str, max_lines: int = 34):
    lines = output.rstrip().splitlines()[-max_lines:]
    body = (f'<span class="p">PS GoldenRecord&gt;</span> {html.escape(command)}\n' +
            html.escape("\n".join(lines)).replace(" passed", ' <span class="ok">passed</span>'))
    doc = (f"<html><head><style>{TERM_CSS}</style></head><body><div class='bar'>"
           "<span class='dot' style='background:#FF5F57'></span><span class='dot' style='background:#FEBC2E'></span>"
           f"<span class='dot' style='background:#28C840'></span>&nbsp;{html.escape(title)}</div><pre>{body}</pre></body></html>")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content(doc)
    page.screenshot(path=str(OUT / f"{name}.png"))
    page.close()
    print("frame", name)


CODE_CSS = """body{margin:0;background:#F6F4EE;width:1920px;height:1080px;font-family:'Segoe UI',sans-serif;}
.head{padding:36px 60px 14px;} .eb{font:700 18px 'Segoe UI';letter-spacing:3px;color:#8A5F00;text-transform:uppercase}
h1{margin:6px 0 0;font-size:40px;color:#0F1B2D} .sub{font-size:21px;color:#4A5263;margin-top:6px}
pre{margin:14px 60px;background:#0F1B2D;color:#E6EDF3;border-radius:14px;padding:26px 32px;font:19px/1.42 'Cascadia Mono',Consolas,monospace;
white-space:pre-wrap;height:760px;overflow:hidden}
.c{color:#8B949E}.k{color:#E8B84A}"""


def code_frame(browser, name: str, eyebrow: str, title: str, sub: str, code: str, max_lines: int = 30):
    lines = code.splitlines()[:max_lines]
    out = []
    for ln in lines:
        e = html.escape(ln)
        out.append(f'<span class="c">{e}</span>' if ln.lstrip().startswith(("#", "--")) else e)
    body = "\n".join(out)
    for kw in ("CONSTRAINT", "CHECK", "ON MISMATCH DROP", "MATERIALIZED LAKE VIEW", "ai.generate_response",
               "FabricAIFunctionsLLM", "IsolationForest"):
        body = body.replace(kw, f'<span class="k">{kw}</span>')
    doc = (f"<html><head><style>{CODE_CSS}</style></head><body><div class='head'><div class='eb'>{eyebrow}</div>"
           f"<h1>{html.escape(title)}</h1><div class='sub'>{html.escape(sub)}</div></div><pre>{body}</pre></body></html>")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content(doc)
    page.screenshot(path=str(OUT / f"{name}.png"))
    page.close()
    print("frame", name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        s = Shooter(page)

        # 1. The state after the first (bootstrap) run
        s.goto("Overview"); s.shot("10_overview_first_run")
        s.goto("Pattern queue"); s.shot("11_pattern_queue")
        page.get_by_text("currency '(blank)'").first.click(); s.settle(1.5); s.shot("12_pattern_expanded")

        # 2. Steward approves the patterns (one decision per pattern), then the pipeline reruns
        from goldenrecord.reference import CITY_ALIASES
        decided = 0
        for pat in call("GET", "/patterns?limit=200"):
            canon = None
            if pat["kind"] == "value_mapping" and pat["needs_input"]:
                canon = CITY_ALIASES.get(pat["signature"].split(":", 1)[1]) if pat["signature"].startswith("city:") else None
                if canon is None:
                    continue
            call("POST", f"/patterns/{pat['pattern_id']}/decision",
                 {"decision": "approve", "reviewer": "demo-steward", "canonical": canon})
            decided += 1
        run2 = call("POST", "/runs")["summary"]
        print("decisions", decided, "rerun", {k: run2[k] for k in ("records_fixed", "golden_vendors", "llm_calls")})
        s.goto("Overview"); s.shot("20_overview_after_patterns")
        s.goto("Rule library"); s.shot("21_rule_library")
        s.goto("Executive spend"); s.shot("22_executive_spend")

        # 3. Break it: a wrong plain-English rule
        s.goto("Rule studio")
        box = page.get_by_role("textbox", name="Rule")
        box.fill("Invoice amount must not exceed 1,000")
        box.press("Enter"); s.settle(1)
        page.get_by_text("Preview impact").click(); s.settle(3)
        s.shot("30_rule_blocked")

        # 4. Break it: a false merge by a tired steward, detected, explained, undone
        pairs = json.loads(docker_py(
            "from goldenrecord.store import Lakehouse;import json;p=Lakehouse().read('silver_match_pairs');"
            "w=p[p['tax_conflict']==True].iloc[0];print(json.dumps([w['left_key'],w['right_key']]))"))
        call("POST", "/review/decisions", {"left_key": pairs[0], "right_key": pairs[1], "decision": "match",
                                           "reviewer": "tired-steward"})
        call("POST", "/runs")
        s.goto("Golden records"); s.shot("40_suspect_merge")
        page.get_by_text("Explain").click(); s.settle(3); s.shot("41_explain_merge", scroll_to="Detach member")
        call("POST", "/golden/unmerge", {"record_key": pairs[1], "reviewer": "lead-steward"})
        run_u = call("POST", "/runs")["summary"]
        print("after unmerge suspects", run_u["suspect_golden_records"])
        s.goto("Golden records"); s.shot("42_after_unmerge")

        # 5. A bad batch arrives: the Sentinel raises a per-source alert
        call("POST", "/demo/bad-batch?rows=3000")
        run3 = call("POST", "/runs")["summary"]
        print("bad batch alerts", run3["alerts"])
        s.goto("Alerts & agents"); s.shot("50_alerts")
        call("DELETE", "/demo/bad-batch")
        call("POST", "/runs")

        # 6. Terminal evidence: tests and the measured comparison
        py = str(ROOT / ".venv" / "Scripts" / "python.exe")
        tests = subprocess.run([py, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=900)
        terminal_frame(browser, "60_tests", "pytest · GoldenRecord", "python -m pytest -q", tests.stdout)
        abl = subprocess.run([py, "-m", "goldenrecord", "ablation"], cwd=ROOT, capture_output=True, text=True,
                             timeout=900, env={**__import__("os").environ, "MLFLOW_DISABLE_AGENT_HINT": "1"})
        terminal_frame(browser, "61_ablation", "Measured comparison · same seeded dataset",
                       "python -m goldenrecord ablation", abl.stdout, max_lines=34)

        # 7. The Fabric side: the notebook and the generated constraint SQL
        nb = (ROOT / "fabric" / "notebooks" / "nb_04_resolve_and_remediate.py").read_text(encoding="utf-8")
        code_frame(browser, "70_fabric_notebook", "Fabric notebook · nb_04",
                   "The same agents run inside Fabric",
                   "FabricLakehouse (OneLake Delta tables) + FabricAIFunctionsLLM (AI Functions, no keys)", nb)
        sys.path.insert(0, str(ROOT / "src"))
        from goldenrecord.fabric_sql import mlv_invoice_valid
        code_frame(browser, "71_mlv_sql", "Native detection · materialized lake view",
                   "Constraints generated from one rule catalog",
                   "Tested to fail exactly the records the local engine fails", mlv_invoice_valid())
        browser.close()


if __name__ == "__main__":
    main()
