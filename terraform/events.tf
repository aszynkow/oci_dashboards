resource "oci_streaming_stream_pool" "events" {
  compartment_id = var.telemetry_compartment_id
  name           = "backup-events-${var.scope_id}"
}
# Retain the existing pool address even when reusing a stream. A previous failed
# apply can already have created it; never propose deleting that partial success.
resource "oci_streaming_stream" "events" {
  count              = var.existing_stream_id == null ? 1 : 0
  stream_pool_id     = oci_streaming_stream_pool.events.id
  name               = "backup-events-${var.scope_id}"
  partitions         = 1
  retention_in_hours = var.stream_retention_hours
}
moved {
  from = oci_streaming_stream.events
  to   = oci_streaming_stream.events[0]
}
data "oci_streaming_stream" "existing" {
  count     = var.existing_stream_id == null ? 0 : 1
  stream_id = var.existing_stream_id
  lifecycle {
    postcondition {
      condition     = self.state == "ACTIVE"
      error_message = "The selected existing stream must be ACTIVE and accessible in the profile region."
    }
  }
}
locals {
  events_stream_id             = var.existing_stream_id != null ? data.oci_streaming_stream.existing[0].id : oci_streaming_stream.events[0].id
  events_stream_compartment_id = var.existing_stream_id != null ? data.oci_streaming_stream.existing[0].compartment_id : var.telemetry_compartment_id
  completion_types = [
    "com.oraclecloud.blockvolumes.createvolumebackup.end",
    "com.oraclecloud.blockvolumes.copyvolumebackup.end"
  ]
  events_statements = [
    for compartment in var.inventory_compartment_ids :
    "Allow any-user to {STREAM_READ, STREAM_PRODUCE} in compartment id ${local.events_stream_compartment_id} where all {request.principal.type='eventrule', request.principal.compartment.id='${compartment}', target.stream.id='${local.events_stream_id}'}"
  ]
}
resource "oci_identity_policy" "events" {
  provider       = oci.home
  count          = var.create_iam_policy ? 1 : 0
  compartment_id = var.iam_policy_compartment_id
  name           = "backup-events-producer-${var.scope_id}"
  description    = "Event rules in the selected source compartments can write only the backup event stream"
  statements     = local.events_statements
}
resource "oci_events_rule" "completion" {
  for_each       = toset(var.inventory_compartment_ids)
  compartment_id = each.value
  display_name   = "backup-completion-${var.scope_id}"
  description    = "Native backup/copy end events; exact compartment allowlist, including unknown status"
  is_enabled     = true
  condition = jsonencode({
    eventType = local.completion_types
    data      = { compartmentId = [each.value] }
  })
  actions {
    action {
      action_type = "OSS"
      is_enabled  = true
      stream_id   = local.events_stream_id
    }
  }
  # Set up parsing, connector and permissions before enabling capture.
  depends_on = [oci_sch_service_connector.health, oci_identity_policy.events]
}
