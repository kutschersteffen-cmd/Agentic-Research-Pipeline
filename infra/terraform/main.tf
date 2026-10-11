# Production on GCP, single-VM shape (see infra/terraform/README.md).
#
#   browser ─► HTTPS LB + IAP ─► VM (docker compose: frontend :80, backend :8000)
#                                 │  persistent disk at /var/lib/docker (named volumes = run state)
#                                 ├─► Cloud SQL Postgres 16 + pgvector (private IP)
#                                 └─► Cloud NAT ─► Anthropic, SEC EDGAR, GDELT, IR sites
#
# ponytail: one VM because run state lives on local disk and runs/schedulers
# live in the API process. Moving to Cloud Run needs those on GCS + Jobs first.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Create the bucket once by hand, then uncomment:
  # backend "gcs" { bucket = "<project>-tfstate", prefix = "arp" }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  name = "arp-${var.env}"
}

resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "iap.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------- network

resource "google_compute_network" "vpc" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "main" {
  name                     = local.name
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

# The VM has no public IP; all outbound traffic leaves through NAT, logged,
# so crawl traffic to arbitrary IR sites is auditable.
resource "google_compute_router" "main" {
  name    = local.name
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "main" {
  name                               = local.name
  router                             = google_compute_router.main.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  log_config {
    enable = true
    filter = "ALL"
  }
}

# Google's LB health-check / proxy ranges, to the two app ports only.
resource "google_compute_firewall" "lb_to_app" {
  name          = "${local.name}-lb-to-app"
  network       = google_compute_network.vpc.id
  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
  target_tags   = ["arp-app"]
  allow {
    protocol = "tcp"
    ports    = ["80", "8000"]
  }
}

# SSH only through IAP TCP forwarding (`gcloud compute ssh --tunnel-through-iap`).
resource "google_compute_firewall" "iap_ssh" {
  name          = "${local.name}-iap-ssh"
  network       = google_compute_network.vpc.id
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["arp-app"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# Private services access, so Cloud SQL gets an IP inside the VPC.
resource "google_compute_global_address" "sql_range" {
  name          = "${local.name}-sql-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_range.name]
}

# ---------------------------------------------------------------- database

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "pg" {
  name                = local.name
  database_version    = "POSTGRES_16"
  deletion_protection = true
  depends_on          = [google_service_networking_connection.sql]

  settings {
    tier              = var.db_tier
    availability_type = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    insights_config {
      query_insights_enabled = true
    }
  }
}

# pgvector ships with Cloud SQL; `arp db init-postgres` runs CREATE EXTENSION itself.
resource "google_sql_database" "arp" {
  name     = "arp"
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "arp" {
  name     = "arp"
  instance = google_sql_database_instance.pg.name
  password = random_password.db.result
}

# ---------------------------------------------------------------- secrets

# Terraform creates the secret, not its value: add the key with
#   printf %s "$KEY" | gcloud secrets versions add arp-prod-anthropic-api-key --data-file=-
# so it never lands in Terraform state.
resource "google_secret_manager_secret" "anthropic" {
  secret_id = "${local.name}-anthropic-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "postgres_dsn" {
  secret_id = "${local.name}-postgres-dsn"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "postgres_dsn" {
  secret      = google_secret_manager_secret.postgres_dsn.id
  secret_data = "postgresql+psycopg://arp:${random_password.db.result}@${google_sql_database_instance.pg.private_ip_address}:5432/arp?sslmode=require"
}

# ---------------------------------------------------------------- images

resource "google_artifact_registry_repository" "images" {
  repository_id = local.name
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ---------------------------------------------------------------- VM

resource "google_service_account" "vm" {
  account_id   = "${local.name}-vm"
  display_name = "ARP app VM"
}

resource "google_project_iam_member" "vm" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.value
  member   = google_service_account.vm.member
}

resource "google_artifact_registry_repository_iam_member" "vm_pull" {
  repository = google_artifact_registry_repository.images.name
  location   = var.region
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.vm.member
}

resource "google_secret_manager_secret_iam_member" "vm" {
  for_each  = { anthropic = google_secret_manager_secret.anthropic.id, dsn = google_secret_manager_secret.postgres_dsn.id }
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.vm.member
}

# All run state (runs/, taxonomies/, documents, caches) lives in Docker named
# volumes, so this disk is mounted at /var/lib/docker and snapshotted daily.
resource "google_compute_disk" "data" {
  name = "${local.name}-data"
  type = "pd-balanced"
  size = var.data_disk_gb
}

resource "google_compute_resource_policy" "daily_snapshot" {
  name = "${local.name}-daily-snapshot"
  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "02:00"
      }
    }
    retention_policy {
      max_retention_days    = var.snapshot_retention_days
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }
  }
}

resource "google_compute_disk_resource_policy_attachment" "data" {
  name = google_compute_resource_policy.daily_snapshot.name
  disk = google_compute_disk.data.name
}

resource "google_compute_instance" "app" {
  name         = local.name
  machine_type = var.machine_type
  tags         = ["arp-app"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 50
    }
  }

  attached_disk {
    source      = google_compute_disk.data.id
    device_name = "arp-data"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.id
    # no access_config: no public IP
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
  }
  metadata_startup_script = file("${path.module}/startup.sh")

  allow_stopping_for_update = true
}

# ---------------------------------------------------------------- load balancer + IAP

resource "google_compute_instance_group" "app" {
  name      = local.name
  instances = [google_compute_instance.app.self_link]
  named_port {
    name = "web"
    port = 80
  }
  named_port {
    name = "api"
    port = 8000
  }
}

# The health check sends Host: <domain>, because the API's TrustedHostMiddleware
# rejects any host not in ARP_TRUSTED_HOSTS (set that to ["<domain>"]).
resource "google_compute_health_check" "web" {
  name = "${local.name}-web"
  http_health_check {
    port         = 80
    request_path = "/"
    host         = var.domain
  }
}

resource "google_compute_health_check" "api" {
  name = "${local.name}-api"
  http_health_check {
    port         = 8000
    request_path = "/api/health"
    host         = var.domain
  }
}

resource "google_compute_backend_service" "web" {
  name                  = "${local.name}-web"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  port_name             = "web"
  health_checks         = [google_compute_health_check.web.id]
  backend {
    group = google_compute_instance_group.app.id
  }
  iap {
    enabled = true
  }
  log_config {
    enable = true
  }
}

resource "google_compute_backend_service" "api" {
  name                  = "${local.name}-api"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  port_name             = "api"
  health_checks         = [google_compute_health_check.api.id]
  timeout_sec           = 300 # deck rendering and large exports run long
  backend {
    group = google_compute_instance_group.app.id
  }
  iap {
    enabled = true
  }
  log_config {
    enable = true
  }
}

# Same origin for UI and API: build the frontend with VITE_API_BASE=https://<domain>.
resource "google_compute_url_map" "main" {
  name            = local.name
  default_service = google_compute_backend_service.web.id
  host_rule {
    hosts        = [var.domain]
    path_matcher = "app"
  }
  path_matcher {
    name            = "app"
    default_service = google_compute_backend_service.web.id
    path_rule {
      paths   = ["/api", "/api/*"]
      service = google_compute_backend_service.api.id
    }
  }
}

resource "google_compute_managed_ssl_certificate" "main" {
  name = local.name
  managed {
    domains = [var.domain]
  }
}

resource "google_compute_ssl_policy" "modern" {
  name            = local.name
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"
}

resource "google_compute_target_https_proxy" "main" {
  name             = local.name
  url_map          = google_compute_url_map.main.id
  ssl_certificates = [google_compute_managed_ssl_certificate.main.id]
  ssl_policy       = google_compute_ssl_policy.modern.id
}

resource "google_compute_global_address" "lb" {
  name = local.name
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = local.name
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_https_proxy.main.id
  ip_address            = google_compute_global_address.lb.id
  port_range            = "443"
}

# Who gets past IAP at all. The app's own sign-in (ARP_AUTH_MODE=local) still
# decides viewer / analyst / approver behind it.
resource "google_iap_web_iam_member" "access" {
  for_each = toset(var.iap_members)
  role     = "roles/iap.httpsResourceAccessor"
  member   = each.value
}
