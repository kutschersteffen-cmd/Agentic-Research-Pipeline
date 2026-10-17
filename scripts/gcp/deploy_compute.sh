#!/usr/bin/env bash
# Builds backend/Dockerfile.compute with Cloud Build and deploys the arp-parse and arp-models Cloud Run
# GPU services from it (arp/compute/server.py). Run by .github/workflows/deploy-compute.yml on every
# relevant push to main, and once by setup_compute.sh.
# Needs PROJECT and TAG (the commit's first 7 SHA characters); REGION defaults to europe-west1.
set -euo pipefail

: "${PROJECT:?set PROJECT}" "${TAG:?set TAG}"
REGION="${REGION:-europe-west1}"
BUCKET="${BUCKET:-$PROJECT-arp-compute}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/arp/compute:$TAG"
cd "$(dirname "$0")/../.."

gcloud builds submit . --project "$PROJECT" --region "$REGION" \
  --config scripts/gcp/cloudbuild.yaml --substitutions "_IMAGE=$IMAGE"

# GPU services need instance-based billing (--no-cpu-throttling) and at least 4 CPU / 16 GiB.
# 2 parse + 1 models instances = the 3 L4 GPUs a new project gets without a quota request.
common=(
  --project "$PROJECT" --region "$REGION" --image "$IMAGE" --quiet
  --no-allow-unauthenticated
  --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy
  --cpu 4 --memory 16Gi --no-cpu-throttling --min-instances 0
  --service-account "arp-compute@$PROJECT.iam.gserviceaccount.com"
)
# Concurrency 1: parallel parses fan out to separate GPUs (the client keeps at most 2 in flight).
gcloud run deploy arp-parse "${common[@]}" --max-instances 2 --concurrency 1 --timeout 3600 \
  --add-volume "name=docs,type=cloud-storage,bucket=$BUCKET,readonly=true" \
  --add-volume-mount "volume=docs,mount-path=/gcs"
gcloud run deploy arp-models "${common[@]}" --max-instances 1 --concurrency 8 --timeout 300
