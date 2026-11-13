variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Dev tier for the design-partner window; scale at platform GA (PRD §12 M10+)."
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Application DB user password — supplied from the operator environment, never committed."
}
