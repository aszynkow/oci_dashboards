resource "oci_log_analytics_log_analytics_log_group" "health" {
  compartment_id = var.telemetry_compartment_id
  namespace      = local.log_analytics_namespace
  display_name   = "Block Backup Activity ${var.scope_id}"
  description    = "Native backup completion events; operation outcomes do not prove current recovery coverage"
  depends_on     = [data.oci_log_analytics_namespace.health]
}

# Inert compatibility marker for prior partial applies. It has no provisioners,
# triggers or OCI side effects. Retaining its address preserves existing state.
# Log Analytics schema setup is now owned by the Python deployer before apply.
resource "terraform_data" "native_schema" {
  input = { owner = "oci-dashboards-native-schema-v1" }
}
locals {
  connector_iam_statements = [
    "Allow any-user to {STREAM_READ, STREAM_CONSUME} in compartment id ${local.events_stream_compartment_id} where all {request.principal.type='serviceconnector', request.principal.compartment.id='${var.telemetry_compartment_id}', target.stream.id='${local.events_stream_id}'}",
    "Allow any-user to {LOG_ANALYTICS_LOG_GROUP_UPLOAD_LOGS} in compartment id ${var.telemetry_compartment_id} where all {request.principal.type='serviceconnector', request.principal.compartment.id='${var.telemetry_compartment_id}', target.loganalytics-log-group.id='${oci_log_analytics_log_analytics_log_group.health.id}'}"
  ]
}
resource "oci_identity_policy" "connector" {
  provider       = oci.home
  count          = var.create_iam_policy ? 1 : 0
  compartment_id = var.iam_policy_compartment_id
  name           = "backup-health-connector-${var.scope_id}"
  description    = "Connector can consume only this stream and upload only to the destination analytics group"
  statements     = local.connector_iam_statements
}
resource "oci_sch_service_connector" "health" {
  compartment_id = var.telemetry_compartment_id
  display_name   = "backup-events-${var.scope_id}"
  description    = "Native Events stream to Log Analytics; no Functions task"
  state          = "ACTIVE"
  source {
    kind      = "streaming"
    stream_id = local.events_stream_id
    cursor { kind = "TRIM_HORIZON" }
  }
  target {
    kind                  = "loggingAnalytics"
    log_group_id          = oci_log_analytics_log_analytics_log_group.health.id
    log_source_identifier = var.native_source_name
  }
  depends_on = [oci_identity_policy.connector]
}
resource "oci_management_dashboard_management_dashboards_import" "health" {
  import_details = replace(replace(replace(file(var.dashboard_import_file),
    "__BH_ANALYTICS_LOG_GROUP_ID__", oci_log_analytics_log_analytics_log_group.health.id),
    "__BH_TELEMETRY_COMPARTMENT_ID__", var.telemetry_compartment_id),
  "__BH_DASHBOARD_COMPARTMENT_ID__", var.dashboard_compartment_id)
  override_same_name                     = "true"
  override_dashboard_compartment_ocid    = var.dashboard_compartment_id
  override_saved_search_compartment_ocid = var.dashboard_compartment_id
  depends_on                             = [oci_sch_service_connector.health]
}
