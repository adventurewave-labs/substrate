# Secret *containers* are terraformed; the secret *versions* (the actual values) are
# pushed from the remote plane so no credential ever transits this repo:
#
#   printf 'postgresql://substrate_app:<pw>@<private-ip>:5432/substrate' \
#     | gcloud secrets versions add substrate-database-url --data-file=-
resource "google_secret_manager_secret" "database_url" {
  secret_id = "substrate-database-url"

  replication {
    auto {}
  }
}
