# Optional resources use count so enabling coverage does not move activity state.
resource "oci_log_analytics_log_analytics_log_group" "coverage" {
  count          = var.enable_coverage ? 1 : 0
  compartment_id = var.telemetry_compartment_id
  namespace      = local.log_analytics_namespace
  display_name   = "Block Backup Coverage ${var.scope_id}"
  depends_on     = [data.oci_log_analytics_namespace.health]
}
resource "oci_functions_application" "coverage" {
  count          = var.enable_coverage ? 1 : 0
  compartment_id = var.telemetry_compartment_id
  display_name   = "backup-coverage-${var.scope_id}"
  subnet_ids     = var.coverage_subnet_ids
  shape          = "GENERIC_X86"
  lifecycle {
    precondition {
      condition     = length(var.coverage_subnet_ids) > 0 && var.coverage_function_image != null
      error_message = "Coverage requires existing subnet IDs and a pre-published Function image."
    }
  }
}
# Runtime diagnostics are OCI Logging service logs, separate from the inventory
# snapshots in Log Analytics. Functions forwards stdout/stderr automatically.
resource "oci_logging_log_group" "coverage" {
  count          = var.enable_coverage ? 1 : 0
  compartment_id = var.telemetry_compartment_id
  display_name   = "backup-coverage-runtime-${var.scope_id}"
  description    = "Coverage Function invocation and collection diagnostics"
}
resource "oci_logging_log" "coverage" {
  count              = var.enable_coverage ? 1 : 0
  log_group_id       = oci_logging_log_group.coverage[0].id
  display_name       = "backup-coverage-${var.scope_id}-invoke"
  log_type           = "SERVICE"
  is_enabled         = true
  retention_duration = 30
  configuration {
    compartment_id = var.telemetry_compartment_id
    source {
      source_type = "OCISERVICE"
      service     = "functions"
      resource    = oci_functions_application.coverage[0].id
      category    = "invoke"
    }
  }
}
resource "oci_functions_function" "coverage" {
  count                            = var.enable_coverage ? 1 : 0
  application_id                   = oci_functions_application.coverage[0].id
  display_name                     = "backup-coverage-${var.scope_id}"
  memory_in_mbs                    = 512
  timeout_in_seconds               = 300
  detached_mode_timeout_in_seconds = 1800
  source_details {
    source_type  = "CONTAINER_IMAGE"
    image        = var.coverage_function_image
    image_digest = var.coverage_function_image_digest
  }
  config = {
    COVERAGE_CONFIG = jsonencode({
      scope_id                  = var.scope_id
      region                    = var.region
      telemetry_compartment_id  = var.telemetry_compartment_id
      inventory_compartment_ids = var.inventory_compartment_ids
      coverage_regions          = length(var.coverage_regions) > 0 ? var.coverage_regions : [var.region]
      coverage_settings         = var.coverage_settings
      coverage_log_group_id     = oci_log_analytics_log_analytics_log_group.coverage[0].id
      log_analytics_namespace   = local.log_analytics_namespace
    })
  }
}
resource "oci_resource_scheduler_schedule" "coverage" {
  count              = var.enable_coverage ? 1 : 0
  compartment_id     = var.telemetry_compartment_id
  display_name       = "backup-coverage-${var.scope_id}"
  action             = "START_RESOURCE"
  recurrence_type    = "CRON"
  local_time_zone    = "UTC"
  recurrence_details = var.coverage_schedule
  state              = "ACTIVE"
  resources {
    id = oci_functions_function.coverage[0].id
  }
  depends_on = [oci_logging_log.coverage]
}
resource "oci_identity_dynamic_group" "coverage_function" {
  provider       = oci.home
  count          = var.enable_coverage && var.create_iam_policy ? 1 : 0
  compartment_id = var.iam_policy_compartment_id
  name           = "backup-coverage-function-${var.scope_id}"
  description    = "Only this read-only coverage Function"
  matching_rule  = "ALL {resource.type='fnfunc', resource.id='${oci_functions_function.coverage[0].id}'}"
}
resource "oci_identity_dynamic_group" "coverage_schedule" {
  provider       = oci.home
  count          = var.enable_coverage && var.create_iam_policy ? 1 : 0
  compartment_id = var.iam_policy_compartment_id
  name           = "backup-coverage-schedule-${var.scope_id}"
  description    = "Only this coverage resource schedule"
  matching_rule  = "ALL {resource.type='resourceschedule', resource.id='${oci_resource_scheduler_schedule.coverage[0].id}'}"
}
locals {
  coverage_function_group = "backup-coverage-function-${var.scope_id}"
  coverage_schedule_group = "backup-coverage-schedule-${var.scope_id}"
  coverage_iam_statements = !var.enable_coverage ? [] : concat(flatten([
    for compartment in var.inventory_compartment_ids : [
      for resource in ["volumes", "volume-backups", "volume-groups", "volume-group-backups", "backup-policy-assignments"] :
      "Allow dynamic-group ${local.coverage_function_group} to read ${resource} in compartment id ${compartment}"
    ]
    ]), [
    "Allow dynamic-group ${local.coverage_function_group} to {LOG_ANALYTICS_LOG_GROUP_UPLOAD_LOGS} in compartment id ${var.telemetry_compartment_id} where target.loganalytics-log-group.id='${oci_log_analytics_log_analytics_log_group.coverage[0].id}'",
    "Allow dynamic-group ${local.coverage_function_group} to {METRIC_WRITE} in compartment id ${var.telemetry_compartment_id} where target.metrics.namespace='backup_coverage'",
    "Allow dynamic-group ${local.coverage_schedule_group} to {FN_FUNCTION_READ, FN_INVOCATION} in compartment id ${var.telemetry_compartment_id} where target.function.id='${oci_functions_function.coverage[0].id}'"
  ])
}
resource "oci_identity_policy" "coverage" {
  provider       = oci.home
  count          = var.enable_coverage && var.create_iam_policy ? 1 : 0
  compartment_id = var.iam_policy_compartment_id
  name           = "backup-coverage-${var.scope_id}"
  description    = "Read-only inventory, scoped telemetry writes and scheduled invocation"
  statements     = local.coverage_iam_statements
  depends_on     = [oci_identity_dynamic_group.coverage_function, oci_identity_dynamic_group.coverage_schedule]
}
resource "oci_management_dashboard_management_dashboards_import" "coverage" {
  count = var.enable_coverage ? 1 : 0
  import_details = replace(replace(replace(file(var.coverage_dashboard_file),
    "__BC_LOG_GROUP_ID__", oci_log_analytics_log_analytics_log_group.coverage[0].id),
    "__BH_TELEMETRY_COMPARTMENT_ID__", var.telemetry_compartment_id),
  "__BH_DASHBOARD_COMPARTMENT_ID__", var.dashboard_compartment_id)
  override_same_name                     = "true"
  override_dashboard_compartment_ocid    = var.dashboard_compartment_id
  override_saved_search_compartment_ocid = var.dashboard_compartment_id
}
output "coverage_function_id" {
  value = var.enable_coverage ? oci_functions_function.coverage[0].id : null
}
output "coverage_schedule_id" {
  value = var.enable_coverage ? oci_resource_scheduler_schedule.coverage[0].id : null
}
output "coverage_log_group_id" {
  value = var.enable_coverage ? oci_log_analytics_log_analytics_log_group.coverage[0].id : null
}
output "coverage_runtime_log_id" {
  value = var.enable_coverage ? oci_logging_log.coverage[0].id : null
}
output "coverage_runtime_log_group_id" {
  value = var.enable_coverage ? oci_logging_log_group.coverage[0].id : null
}
output "coverage_iam_statements" { value = local.coverage_iam_statements }
