# GCP production (single VM)

One VM runs the existing `backend` and `frontend` images with Docker Compose,
behind an HTTPS load balancer with Identity-Aware Proxy. Postgres is Cloud SQL.
The VM has no public IP: outbound traffic goes through Cloud NAT, and SSH goes
through IAP.

Why a VM and not Cloud Run: run state lives on local disk (`runs/`,
`taxonomies/`, documents), and pipeline runs and schedulers run inside the API
process. Both need code changes before Cloud Run fits; see
`docs/CORPORATE_READINESS_PLAN.md`, Phase 5.

## Apply

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # project_id, domain, iap_members
terraform init && terraform apply
```

Then:

1. Point the domain's A record at the `lb_ip` output. The managed certificate
   becomes active once DNS resolves, after 15–60 minutes.
2. Store the Anthropic key. Terraform creates the secret but no value, so the
   key never enters Terraform state:
   `printf %s "$KEY" | gcloud secrets versions add arp-prod-anthropic-api-key --data-file=-`
3. Configure IAP's OAuth consent screen once in the console
   (Security → Identity-Aware Proxy).

## Deploy the app

Build and push both images to the `image_repo` output, then deploy:

```bash
REPO=$(terraform output -raw image_repo)
DOMAIN=arp.example.com
docker build -f backend/Dockerfile --build-arg EXTRAS=postgres -t $REPO/backend:v1 .
docker build --build-arg VITE_API_BASE=https://$DOMAIN -t $REPO/frontend:v1 frontend
docker push $REPO/backend:v1 && docker push $REPO/frontend:v1
gcloud compute ssh arp-prod --tunnel-through-iap
```

On the VM, run `gcloud auth configure-docker <region>-docker.pkg.dev`. Then
start a compose file that uses those images, with **these backend settings**
instead of the dev ones in the repo's `docker-compose.yml`:

| Setting | Value |
|---|---|
| `ARP_AUTH_MODE` | `local` (plus `config/users.json`). Remove `ARP_DEV_TRUSTED_NETWORKS`: behind a load balancer, dev mode would sign every user in as an approver. |
| `ARP_TRUSTED_HOSTS` | `["<domain>"]`. The health checks send this host. |
| `ARP_ALLOWED_ORIGINS` | `["https://<domain>"]` |
| `ARP_POSTGRES_DSN` | from secret `arp-prod-postgres-dsn` |
| `ARP_ANTHROPIC_API_KEY` | from secret `arp-prod-anthropic-api-key` |
| ports | `80:80` (frontend), `8000:8000` (backend). The firewall only lets in Google's load-balancer ranges. |

No `postgres` service is needed. Run `arp db init-postgres` once inside the
backend container.

## Not included yet

- Superset, OpenSearch, MinIO: these are opt-in, so add them when a feature needs them.
- dev/staging projects: reuse this module with `env = "staging"` in its own project.
- HTTP→HTTPS redirect: port 80 is simply not served.
- Egress allow-list: NAT logs every outbound connection. Firewall restrictions
  can't cover the open-ended IR-site crawls, so they rely on those logs.
