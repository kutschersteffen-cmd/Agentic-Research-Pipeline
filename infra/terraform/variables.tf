variable "project_id" {
  type = string
}

variable "env" {
  type    = string
  default = "prod"
}

variable "region" {
  type    = string
  default = "europe-west3"
}

variable "zone" {
  type    = string
  default = "europe-west3-a"
}

variable "domain" {
  type        = string
  description = "Public host name, e.g. arp.example.com. Point its A record at the lb_ip output."
}

variable "iap_members" {
  type        = list(string)
  description = "Who may reach the app at all, e.g. [\"group:arp-users@example.com\"]."
}

variable "machine_type" {
  type    = string
  default = "e2-standard-8" # docling + headless Chromium + 8 concurrent LLM calls
}

variable "data_disk_gb" {
  type    = number
  default = 500
}

variable "snapshot_retention_days" {
  type    = number
  default = 14
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "db_high_availability" {
  type    = bool
  default = false
}
