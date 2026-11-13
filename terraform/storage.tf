# Raw claim payloads (provenance evidence). Object-store pointers live in
# claims.value_raw_ref; the payloads live here, versioned, tenant-prefix-keyed.
resource "google_storage_bucket" "claims_raw" {
  name                        = "${var.project_id}-substrate-claims-raw"
  location                    = var.region
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}
