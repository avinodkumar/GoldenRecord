#!/usr/bin/env bash
# Build the goldenrecord wheel and deploy the notebooks and rule config to a Fabric workspace.
# Runs inside the toolbox image:  docker compose --profile deploy run --rm toolbox
#
# Needs in .env: FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET (a service principal with
# Contributor on the workspace), FABRIC_WORKSPACE, FABRIC_LAKEHOUSE.
# NOTE: not yet run against a live workspace; verify each step on first use (roadmap S1-04..S1-06).
set -euo pipefail
cd /app

echo "== 1/4 Tests"
python -m pytest -q tests

echo "== 2/4 Build wheel -> dist/"
python -m build --wheel --outdir dist .

echo "== 3/4 Export notebooks -> build/fabric/"
python deploy/export_notebooks.py

if [[ -z "${FABRIC_CLIENT_ID:-}" || -z "${FABRIC_CLIENT_SECRET:-}" || -z "${FABRIC_TENANT_ID:-}" ]]; then
  echo "Fabric credentials not set: stopping after build. Artifacts are in dist/ and build/fabric/."
  exit 0
fi

echo "== 4/4 Deploy to ${FABRIC_WORKSPACE}"
fab auth login -u "${FABRIC_CLIENT_ID}" -p "${FABRIC_CLIENT_SECRET}" --tenant "${FABRIC_TENANT_ID}"
WS="${FABRIC_WORKSPACE}.Workspace"
for item in build/fabric/*.Notebook; do
  name="$(basename "$item")"
  echo "   importing ${name}"
  fab import "${WS}/${name}" -i "${item}" -f
done
fab cp config/dq_rules.yaml "${WS}/${FABRIC_LAKEHOUSE}.Lakehouse/Files/config/dq_rules.yaml" -f

echo "Done. Upload dist/*.whl to the Environment 'env_goldenrecord' as a custom library and publish it"
echo "(fabric/README.md, step 2), then run nb_01 -> nb_04."
