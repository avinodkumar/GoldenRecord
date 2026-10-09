# Fabric notebook: nb_05_apply_steward_inbox  (runs before nb_02 in the pipeline, and on demand)
# Stewards act in the Power BI report; translytical task flows call User Data Functions that write to the
# Fabric SQL database `sqldb_goldenrecord_steward` (fabric/functions, fabric/sql). The SQL database is
# replicated to OneLake and shortcut into this Lakehouse. This notebook turns each new inbox row into a
# versioned rule-library change, so the next pipeline run applies it to every matching record.

# %% Apply new decisions
from datetime import date, datetime, timezone

import pandas as pd

from goldenrecord.agents.base import AgentContext
from goldenrecord.agents.profiler import ProfilerAgent
from goldenrecord.agents.steward import StewardAssistant
from goldenrecord.fabric_runtime import FabricAIFunctionsLLM, FabricLakehouse

lake = FabricLakehouse(spark)
ctx = AgentContext(lake=lake, llm=FabricAIFunctionsLLM(), run_id="inbox", as_of=date.today())
done = lake.read("inbox_processed")
seen = set() if done.empty else set(zip(done["inbox"], done["inbox_id"]))
steward, profiler, processed = StewardAssistant(), ProfilerAgent(), []

for row in lake.read("pattern_decisions_inbox").to_dict("records"):
    if ("pattern", row["id"]) not in seen:
        r = steward.decide_pattern(ctx, row["pattern_id"], row["decision"], row["reviewer"],
                                   row.get("canonical") or None, row.get("note") or "")
        processed.append({"inbox": "pattern", "inbox_id": row["id"], "result": str(r)})

for row in lake.read("unmerge_inbox").to_dict("records"):
    if ("unmerge", row["id"]) not in seen:
        r = steward.unmerge(ctx, row["record_key"], row["reviewer"], row.get("note") or "")
        processed.append({"inbox": "unmerge", "inbox_id": row["id"], "result": str(r)})

for row in lake.read("rule_requests_inbox").to_dict("records"):
    if ("rule", row["id"]) not in seen:
        # accept=False -> preview only; the report shows rule_previews and the steward accepts with a second click
        r = profiler.draft_rule(ctx, row["rule_text"], accept=bool(row.get("accept")),
                                override=bool(row.get("override")), reviewer=row["reviewer"])
        lake.append("rule_previews", pd.DataFrame([{"request_id": row["id"], "rule_text": row["rule_text"],
                                                    "result": str(r), "previewed_at": datetime.now(timezone.utc)}]))
        processed.append({"inbox": "rule", "inbox_id": row["id"], "result": str(r)})

if processed:
    lake.append("inbox_processed", pd.DataFrame(processed).assign(processed_at=datetime.now(timezone.utc)))
print(f"applied {len(processed)} steward actions")
