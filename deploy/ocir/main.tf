terraform {
  required_version = ">= 1.5.0"
  required_providers {
    oci = { source = "oracle/oci" }
  }
}
variable "oci_profile" { type = string }
variable "region" { type = string }
variable "tenancy_id" { type = string }
variable "compartment_id" { type = string }
variable "repository_name" { type = string }
variable "existing_repository_id" {
  type    = string
  default = null
}
provider "oci" {
  auth                = "APIKey"
  config_file_profile = var.oci_profile
  region              = var.region
}
data "oci_objectstorage_namespace" "tenancy" { compartment_id = var.tenancy_id }
resource "oci_artifacts_container_repository" "coverage" {
  count          = var.existing_repository_id == null ? 1 : 0
  compartment_id = var.compartment_id
  display_name   = var.repository_name
  is_public      = false
  # OCI exposes is_immutable in the schema but does not support setting it.
  freeform_tags = { managed_by = "oci_dashboards_coverage" }
  lifecycle { prevent_destroy = true }
}
data "oci_artifacts_container_repository" "existing" {
  count         = var.existing_repository_id == null ? 0 : 1
  repository_id = var.existing_repository_id
  lifecycle {
    postcondition {
      condition     = self.compartment_id == var.compartment_id && self.display_name == var.repository_name && !self.is_public
      error_message = "Existing repository must be private and match the selected name and compartment."
    }
  }
}
output "repository_id" {
  value = var.existing_repository_id == null ? oci_artifacts_container_repository.coverage[0].id : data.oci_artifacts_container_repository.existing[0].id
}
output "namespace" { value = data.oci_objectstorage_namespace.tenancy.namespace }
