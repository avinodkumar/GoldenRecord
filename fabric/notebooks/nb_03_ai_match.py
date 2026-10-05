# Fabric notebook: nb_03_ai_match  (pandas + Fabric AI Functions)
# Deliverable 2: every candidate pair gets a match decision, a confidence band and an explanation.
#
# Guardrail: the deterministic score comes first. AI Functions only review the grey zone, and the
# AI can raise a pair to HIGH only when the rules still agree (no conflicting tax IDs, same country).

# %% Parameters
from goldenrecord.config import GREY_ZONE
GREY_LOW, GREY_HIGH = GREY_ZONE   # pairs in this score range go to the AI

# %% Imports
import pandas as pd
import synapse.ml.aifunc as aifunc  # noqa: F401  (registers the .ai accessor)

from goldenrecord.matching import assign_band, candidate_pairs, score_pairs

vendors = spark.table("silver_vendor").toPandas()

# %% 1. Blocking + deterministic features and score
pairs = score_pairs(vendors, candidate_pairs(vendors))
print(pairs["band"].value_counts())

# %% 2. AI review of the grey zone
v = vendors.set_index("record_key")
grey = pairs[(pairs["score"] >= GREY_LOW) & (pairs["score"] < GREY_HIGH)].copy()
for side in ("left", "right"):
    keys = grey[f"{side}_key"]
    grey[f"{side}_desc"] = (v.loc[keys, "vendor_name"].fillna("").values + ", "
                            + v.loc[keys, "city"].fillna("").values + ", "
                            + v.loc[keys, "country_iso2"].fillna("").values)

grey["ai_similarity"] = grey["left_name"].ai.similarity(grey["right_name"])
grey["pair_text"] = "Record 1: " + grey["left_desc"] + " | Record 2: " + grey["right_desc"]
grey["ai_decision"] = grey["pair_text"].ai.classify("same vendor", "different vendor")
grey["ai_explanation"] = grey[["pair_text", "explanation"]].ai.generate_response(
    "In one sentence for a data steward, explain whether these two vendor records are the same "
    "company. Use the evidence column; do not invent facts."
)

# %% 3. Rules decide: the same guardrail the local Gatekeeper agent uses (ADR 0002)
from goldenrecord.matching import guarded_band

grey["ai_label"] = grey["ai_decision"].map({"same vendor": "same", "different vendor": "different"})
grey["band"] = [guarded_band(s, tc, d, sim) for s, tc, d, sim in
                zip(grey["score"], grey["tax_conflict"], grey["ai_label"], grey["ai_similarity"])]
grey["explanation"] = grey["ai_explanation"].fillna(grey["explanation"])

out = pairs.drop(columns=["band", "explanation"]).merge(
    grey[["left_key", "right_key", "band", "explanation", "ai_similarity", "ai_decision"]],
    on=["left_key", "right_key"], how="left")
out["band"] = out["band"].fillna(pairs["score"].map(assign_band))
out["explanation"] = out["explanation"].fillna(pairs["explanation"])
out["decided_by"] = out["ai_decision"].map(lambda d: "rules+ai" if isinstance(d, str) else "rules")

spark.createDataFrame(out).write.mode("overwrite").format("delta").saveAsTable("silver_match_pairs")
print(out["band"].value_counts())

# %% Token usage and errors for the AI calls (cost transparency for the demo)
display(grey["ai_decision"].ai.stats)
