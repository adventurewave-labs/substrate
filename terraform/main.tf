provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_compute_network" "substrate" {
  name                    = "substrate-net"
  auto_create_subnetworks = false
}

# Private-services range + VPC peering so Cloud SQL is private-IP only.
resource "google_compute_global_address" "private_ip_alloc" {
  name          = "substrate-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.substrate.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.substrate.id
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
}
