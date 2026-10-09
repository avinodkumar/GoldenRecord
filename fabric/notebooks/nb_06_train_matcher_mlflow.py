# Fabric notebook: nb_06_train_matcher_mlflow  (weekly, Fabric Data Science)
# Steward pair decisions plus clear-cut automatic labels train a match classifier, tracked and registered
# in the workspace's MLflow (experiment + model registry are native Fabric items).

# %% Train
from goldenrecord.fabric_runtime import FabricLakehouse
from goldenrecord.learning import train_matcher

lake = FabricLakehouse(spark)
result = train_matcher(lake.read("silver_match_pairs"), lake.read("steward_decisions"), tracking_uri="fabric")
print(result)
