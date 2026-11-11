terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source = "oracle/oci"
    }
  }
}

provider "oci" {
  auth                = "APIKey"
  config_file_profile = var.oci_profile
  region              = var.region
}

provider "oci" {
  alias               = "home"
  auth                = "APIKey"
  config_file_profile = var.oci_profile
  region              = local.home_region
}

# This read uses the regional provider, avoiding a dependency on oci.home.
data "oci_identity_region_subscriptions" "tenancy" {
  tenancy_id = var.iam_policy_compartment_id
}
locals {
  home_region = var.home_region != null ? var.home_region : one([
    for subscription in data.oci_identity_region_subscriptions.tenancy.region_subscriptions :
    subscription if subscription.is_home_region
  ]).region_name
}
