resource "google_sql_database_instance" "substrate" {
  name                = "substrate-core"
  database_version    = "POSTGRES_15"
  region              = var.region
  deletion_protection = true

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    disk_size         = 10
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.substrate.id
    }

    backup_configuration {
      enabled = true
    }
  }

  depends_on = [google_service_networking_connection.private_vpc_connection]
}

resource "google_sql_database" "app" {
  name     = "substrate"
  instance = google_sql_database_instance.substrate.name
}

resource "google_sql_user" "app" {
  instance = google_sql_database_instance.substrate.name
  name     = "substrate_app"
  password = var.db_password
}
