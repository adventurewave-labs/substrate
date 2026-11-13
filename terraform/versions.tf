terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }

  # State lives in GCS, applied from the remote plane only (rig law: the Mac is a
  # control plane — no local state, no local applies). Configure on first apply:
  #
  #   backend "gcs" {
  #     bucket = "substrate-tfstate"
  #     prefix = "core"
  #   }
}
