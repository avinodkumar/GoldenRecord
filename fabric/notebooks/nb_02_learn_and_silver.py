# Fabric notebook: nb_02_learn_and_silver  (pipeline step 2)
# Profiler agent: Fabric AI Functions see each DISTINCT unknown value once ("Bangalore", "ENGG", "RS"),
# propose a mapping to a known canonical value, and the answer is cached. Validated, confident mappings
# enter the versioned rule library; the rest become steward patterns. Silver is then a deterministic lookup:
# a rerun with no new values makes zero AI calls.

# %% Run
from datetime import date

import pandas as pd

from goldenrecord import config
from goldenrecord.agents.base import AgentContext
from goldenrecord.agents.orchestrator import _raw_column, build_silver
from goldenrecord.agents.profiler import ProfilerAgent
from goldenrecord.fabric_runtime import FabricAIFunctionsLLM, FabricLakehouse

lake = FabricLakehouse(spark)
llm = FabricAIFunctionsLLM()
run_id = notebookutils.runtime.context.get("currentRunId") or "manual"
ctx = AgentContext(lake=lake, llm=llm, run_id=run_id, as_of=date.today())

bronze = {f"{s}_{e}": lake.read(f"bronze_{s.lower()}_{e}") for s in config.SOURCES for e in ("vendors", "invoices")}
learned = ProfilerAgent().learn_mappings(ctx, _raw_column(bronze, "vendors", "vendor_name"),
                                         _raw_column(bronze, "vendors", "city_raw"),
                                         _raw_column(bronze, "invoices", "currency_raw"))
ctx.flush_events()
vendors, invoices = build_silver(lake, bronze)
print(learned, f"AI calls: {llm.stats.calls}", f"silver: {len(vendors):,} vendors, {len(invoices):,} invoices")
