output "lb_ip" {
  value = google_compute_global_address.lb.address
}

output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "vm_name" {
  value = google_compute_instance.app.name
}

output "db_private_ip" {
  value = google_sql_database_instance.pg.private_ip_address
}

output "secrets" {
  value = {
    anthropic_api_key = google_secret_manager_secret.anthropic.secret_id
    postgres_dsn      = google_secret_manager_secret.postgres_dsn.secret_id
  }
}
