data "oci_objectstorage_namespace" "tenancy" {
  compartment_id = var.iam_policy_compartment_id
}
locals {
  tenancy_namespace       = data.oci_objectstorage_namespace.tenancy.namespace
  log_analytics_namespace = var.log_analytics_namespace != null ? var.log_analytics_namespace : local.tenancy_namespace
}
data "oci_log_analytics_namespace" "health" {
  namespace = local.log_analytics_namespace
  lifecycle {
    postcondition {
      condition     = self.is_onboarded && self.compartment_id == var.iam_policy_compartment_id
      error_message = "Log Analytics must already be onboarded for this tenancy in the profile region."
    }
  }
}
