#!/usr/bin/env bash
# One-time setup of the Cloud Run GPU compute services (arp/compute/) in a GCP project with billing
# enabled. Run it from Git Bash, WSL or a terminal on the machine that runs the ARP backend, logged in
# with `gcloud auth login` as a project owner: it writes the client key next to the backend.
# Idempotent: anything that exists already is kept, and the key file is reused.
#   bash scripts/gcp/setup_compute.sh <project-id>        (BUDGET_AMOUNT=50, REGION=europe-west1)
set -euo pipefail

PROJECT="${1:?usage: bash scripts/gcp/setup_compute.sh <project-id>}"
REGION="${REGION:-europe-west1}"
BUCKET="$PROJECT-arp-compute"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KEY="$REPO_ROOT/backend/.gcp/arp-client.json"
GITHUB_REPO="${GITHUB_REPO:-$(git -C "$REPO_ROOT" remote get-url origin | sed -E 's#\.git$##; s#.*[:/]([^/]+/[^/]+)$#\1#')}"
SA_COMPUTE="arp-compute@$PROJECT.iam.gserviceaccount.com"
SA_CLIENT="arp-client@$PROJECT.iam.gserviceaccount.com"
SA_DEPLOYER="arp-deployer@$PROJECT.iam.gserviceaccount.com"

g() { gcloud --project "$PROJECT" --quiet "$@"; }
exists() { "$@" >/dev/null 2>&1; }

echo "1/10 Billing and APIs"
ACCOUNT="$(g billing projects describe "$PROJECT" --format='value(billingAccountName)')"
ACCOUNT="${ACCOUNT#billingAccounts/}"
[ -n "$ACCOUNT" ] || { echo "Billing is not enabled on $PROJECT; enable it and re-run." >&2; exit 1; }
PROJECT_NUMBER="$(g projects describe "$PROJECT" --format='value(projectNumber)')"
g services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  billingbudgets.googleapis.com cloudresourcemanager.googleapis.com cloudbilling.googleapis.com

echo "2/10 Bucket gs://$BUCKET (objects deleted after 1 day, no soft delete, no versioning)"
exists g storage buckets describe "gs://$BUCKET" ||
  g storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access
LIFECYCLE="$(mktemp)"
echo '{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1}}]}' >"$LIFECYCLE"
g storage buckets update "gs://$BUCKET" --lifecycle-file "$LIFECYCLE" --clear-soft-delete --no-versioning
rm -f "$LIFECYCLE"

echo "3/10 Artifact Registry repo arp"
exists g artifacts repositories describe arp --location "$REGION" ||
  g artifacts repositories create arp --repository-format docker --location "$REGION"

echo "4/10 Service accounts and roles"
for sa in arp-compute arp-client arp-deployer; do
  exists g iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" ||
    g iam service-accounts create "$sa"
done
bucket_role() { g storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$1" --role "$2" >/dev/null; }
bucket_role "$SA_COMPUTE" roles/storage.objectViewer
bucket_role "$SA_CLIENT" roles/storage.objectCreator
bucket_role "$SA_CLIENT" roles/storage.objectViewer
for role in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer roles/storage.admin \
  roles/logging.logWriter roles/logging.viewer roles/serviceusage.serviceUsageConsumer; do
  g projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_DEPLOYER" --role "$role" \
    --condition None >/dev/null
done
# The deployer deploys services running as arp-compute and runs Cloud Build as itself.
for sa in "$SA_COMPUTE" "$SA_DEPLOYER"; do
  g iam service-accounts add-iam-policy-binding "$sa" --member "serviceAccount:$SA_DEPLOYER" \
    --role roles/iam.serviceAccountUser >/dev/null
done

echo "5/10 GitHub Workload Identity Federation for $GITHUB_REPO"
echo "     (must match the repo name on GitHub exactly, capitals included; override with GITHUB_REPO=owner/name)"
POOL="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github"
exists g iam workload-identity-pools describe github --location global ||
  g iam workload-identity-pools create github --location global --display-name "GitHub Actions"
exists g iam workload-identity-pools providers describe github --location global --workload-identity-pool github ||
  g iam workload-identity-pools providers create-oidc github --location global --workload-identity-pool github \
    --issuer-uri https://token.actions.githubusercontent.com \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository == '$GITHUB_REPO'"
g iam service-accounts add-iam-policy-binding "$SA_DEPLOYER" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/$POOL/attribute.repository/$GITHUB_REPO" >/dev/null

echo "6/10 Budget alert arp-compute (${BUDGET_AMOUNT:-50} per month, alerts at 50/90/100 %)"
if ! gcloud billing budgets list --billing-account "$ACCOUNT" --format='value(displayName)' | grep -qx arp-compute; then
  CURRENCY="$(gcloud billing accounts describe "$ACCOUNT" --format='value(currencyCode)')"
  gcloud billing budgets create --billing-account "$ACCOUNT" --display-name arp-compute \
    --budget-amount "${BUDGET_AMOUNT:-50}${CURRENCY}" --filter-projects "projects/$PROJECT" \
    --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
fi

echo "7/10 Build and deploy (Cloud Build; about 20-30 min the first time)"
PROJECT="$PROJECT" REGION="$REGION" BUCKET="$BUCKET" TAG="$(git -C "$REPO_ROOT" rev-parse HEAD | cut -c1-7)" \
  bash "$REPO_ROOT/scripts/gcp/deploy_compute.sh"

echo "8/10 Let arp-client call both services"
for svc in arp-parse arp-models; do
  g run services add-iam-policy-binding "$svc" --region "$REGION" --member "serviceAccount:$SA_CLIENT" \
    --role roles/run.invoker >/dev/null
done

echo "9/10 Client key"
if [ ! -f "$KEY" ]; then
  mkdir -p "$(dirname "$KEY")"
  g iam service-accounts keys create "$KEY" --iam-account "$SA_CLIENT" || {
    echo "Creating a key for $SA_CLIENT failed. The usual cause is the organisation policy" \
      "iam.disableServiceAccountKeyCreation; the key is the blocker." >&2
    exit 1
  }
fi
KEY_PATH="$KEY"
command -v cygpath >/dev/null && KEY_PATH="$(cygpath -w "$KEY")"  # Git Bash: a path Windows Python reads

echo "10/10 Done"
url() { g run services describe "$1" --region "$REGION" --format='value(status.url)'; }
cat <<EOF

Add to backend/.env:
ARP_COMPUTE_PARSE_URL=$(url arp-parse)
ARP_COMPUTE_MODELS_URL=$(url arp-models)
ARP_COMPUTE_BUCKET=$BUCKET
ARP_COMPUTE_CREDENTIALS_FILE=$KEY_PATH
ARP_RERANK_ENABLED=true

Add as GitHub repository variables (Settings > Secrets and variables > Actions > Variables):
GCP_PROJECT=$PROJECT
GCP_REGION=$REGION
GCP_WIF_PROVIDER=$POOL/providers/github
GCP_DEPLOY_SA=$SA_DEPLOYER

Then run: pip install -e backend && arp compute check
EOF
