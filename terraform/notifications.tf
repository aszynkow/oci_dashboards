# Supply existing topic IDs to reuse them; otherwise own one scoped topic.
resource "oci_ons_notification_topic" "health" {
  count          = length(var.alarm_destination_topic_ids) == 0 ? 1 : 0
  compartment_id = var.telemetry_compartment_id
  name           = "backup-health-${var.scope_id}"
  description    = "Optional backup activity topic; subscriptions and alert rules are not provisioned"
}
locals {
  alarm_destination_topic_ids = length(var.alarm_destination_topic_ids) > 0 ? distinct(var.alarm_destination_topic_ids) : oci_ons_notification_topic.health[*].id
}
output "alarm_destination_topic_ids" { value = local.alarm_destination_topic_ids }
