# Fabric notebook: nb_04_resolve_and_remediate  (pipeline step 4): what Fabric does not do natively
#   Quality     flags with reasons (shadow rules report, enforced rules gate)
#   Matcher     deterministic scores; AI Functions only for new grey-zone pairs no library rule covers (cached)
#   Gatekeeper  AI proposes, rules decide; golden records with survivorship and stable master keys;
#               every merge recorded with its reason; suspect merges flagged
#   Steward     thousands of issues grouped into root-cause patterns with one proposed fix each
#   Sentinel    per-source quality scores and alerts (Activator watches dq_source_score_history)
# Then the certified spend view is (re)created on Gold.

# %% Run the agents
from datetime import date

from goldenrecord.agents.base import AgentContext
from goldenrecord.agents.gatekeeper import GatekeeperAgent
from goldenrecord.agents.matcher import MatcherAgent
from goldenrecord.agents.profiler import ProfilerAgent
from goldenrecord.agents.quality import QualityAgent
from goldenrecord.agents.sentinel import SentinelAgent
from goldenrecord.agents.steward import StewardAssistant
from goldenrecord.fabric_runtime import FabricAIFunctionsLLM, FabricLakehouse
from goldenrecord.fabric_sql import mlv_gold_spend

lake = FabricLakehouse(spark)
llm = FabricAIFunctionsLLM()
run_id = notebookutils.runtime.context.get("currentRunId") or "manual"
ctx = AgentContext(lake=lake, llm=llm, run_id=run_id, as_of=date.today())
ctx.state.update(vendors=lake.read("silver_vendor"), invoices=lake.read("silver_invoice"))

results = {}
for agent in (ProfilerAgent(), QualityAgent(), MatcherAgent(), GatekeeperAgent(), StewardAssistant(), SentinelAgent()):
    results[agent.name] = agent.run(ctx)
    ctx.flush_events()
    print(agent.name, results[agent.name])
print(f"AI Functions calls this run: {llm.stats.calls}")

# %% Certified spend view for the semantic model (Gold only)
spark.sql(mlv_gold_spend("dbo"))
display(spark.sql("SELECT COUNT(*) AS invoices, ROUND(SUM(amount_usd), 2) AS spend_usd FROM gold_spend_certified"))
