# Fabric notebook: nb_01_ingest_bronze  (Data Factory pipeline step 1)
# Landing extracts -> Bronze Delta tables with personal data already tokenized and masked.
# Raw PII goes only to pii_vault, readable by the OneLake security role `pii-custodian`.

# %% Parameters
key_vault_uri = "https://<your-key-vault>.vault.azure.net/"
pii_secret_name = "goldenrecord-pii-token-key"

# %% PII token key from Azure Key Vault (never in code or notebook output)
import os
import notebookutils

os.environ["PII_TOKEN_KEY"] = notebookutils.credentials.getSecret(key_vault_uri, pii_secret_name)

# %% Ingest
from datetime import datetime, timezone

from goldenrecord.agents.orchestrator import ingest_bronze
from goldenrecord.fabric_runtime import FabricLakehouse

lake = FabricLakehouse(spark)
bronze = ingest_bronze(lake, datetime.now(timezone.utc))
for name, df in bronze.items():
    print(f"bronze {name}: {len(df):,} rows")
