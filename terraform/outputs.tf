output "analytics_log_group_id" { value = oci_log_analytics_log_analytics_log_group.health.id }
output "connector_id" { value = oci_sch_service_connector.health.id }
output "stream_id" { value = local.events_stream_id }
output "event_rule_ids" { value = { for k, rule in oci_events_rule.completion : k => rule.id } }
output "home_region" { value = local.home_region }
output "tenancy_namespace" { value = local.tenancy_namespace }
output "log_analytics_namespace" { value = local.log_analytics_namespace }
output "native_source_name" { value = var.native_source_name }
output "events_iam_statements" { value = local.events_statements }
output "connector_iam_statements" { value = local.connector_iam_statements }
