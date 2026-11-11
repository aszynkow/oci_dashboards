# Native backup event dashboard deployment

The current implementation replaces the collector with **Events → Streaming → Connector Hub → Log Analytics → native saved searches/dashboard**. The region/tenancy come from the selected profile; Terraform discovers home region and namespace. No deployment was performed during implementation.

## Prerequisites and inputs

- Python 3.10+, project dependencies (`pip install -e .`), Terraform 1.5+ and a current Oracle provider.
- An existing API-key profile in `~/.oci/config`, including `tenancy` and `region`.
- Log Analytics already onboarded in the profile region. Terraform reads and checks it; it never enables/offboards the service automatically.
- `telemetry_compartment_id` for the stream/pool, connector, analytics group and optional notification topic.
- `dashboard_compartment_id` for the dashboard/searches. If omitted, the coordinator uses the telemetry compartment.
- `inventory_compartment_ids` as a nonempty explicit list of native event source compartments. This name is retained for compatibility; no inventory is queried. Rules live in those compartments and filter `data.compartmentId` to exact source matches; include children explicitly.
- `create_iam_policy` defaults to false. Set true for the service policies, or pre-provision equivalent access.

Optional inputs: `existing_stream_id`, `scope_id`, `dashboard_display_name`, `stream_retention_hours` (24..168, default 168), and existing `alarm_destination_topic_ids`. No Function images, network subnets, scheduler, collector flag, backup policy targets or private state are needed. Remove these superseded inputs from older tfvars; unknown inputs fail closed.

One deployment ingests events in the selected profile region. Its displayed source region is that deployment region, not an inferred copy destination. Additional regions require independent deployments and distinct scopes/state directories; central cross-region collection is not claimed.

## Commands and artifacts

```bash
source .venv/bin/activate
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Fill OCIDs, choose create_iam_policy.
python3 scripts/deploy.py --profile YOUR_PROFILE --prepare
python3 scripts/deploy.py --profile YOUR_PROFILE --plan
# Operator action only:
python3 scripts/deploy.py --profile YOUR_PROFILE --apply
```

`--prepare` is default and offline: it reads public profile identifiers and resolves typed tfvars with isolated Terraform console (no provider/backend/cloud). It writes CLI/API dashboard JSON, `native-event-schema.json`, deployment design/identity and a root Terraform JSON wrapper into `build/native-events/`. Profile credentials, keys and live records are not copied. The schema example is synthetic and never ingested.

`--plan` checks placeholders, refreshes cached module copies with `terraform get -update` (without upgrading locked providers), initializes/validates Terraform, reads home/namespace/onboarding metadata and saves a plan. It does not run schema upserts, create resources or import the dashboard. `--apply` repeats the planning checks, directly calls Python schema setup using the namespace resolved in the reviewed plan, then applies only that saved plan after setup succeeds; the apply receipt includes source/target resource IDs and required policy statements. `--output` must stay under ignored `build/`; keep the same state directory for repeats. Files are mode 0600 and the directory 0700. Use an organization-managed remote state backend for shared production operation; no backend credentials are written by the script.

The script refuses real resource deletions/replacements. Two explicit update exceptions exist: the Management Dashboard import wrapper has a verified no-op Delete, and the owned legacy `terraform_data.native_schema` marker is inert, has no provisioners and only updates local Terraform metadata. No remote resource deletion is performed by either exception. Existing stream retention changes may require replacement and must be reviewed independently.

## Ingestion and parsing

Terraform creates a single-partition stream with a dedicated stream pool and seven-day default buffer. Connector Hub uses `streaming` source, `TRIM_HORIZON` cursor and a `loggingAnalytics` target with the generated native source name. Starting at the earliest retained message helps restart/replay; queries deduplicate immutable native event IDs.

Per-compartment Events rules capture both `com.oraclecloud.blockvolumes.createvolumebackup.end` and `com.oraclecloud.blockvolumes.copyvolumebackup.end`. They do not filter status, so missing/new statuses remain visible. Rules start after parsing, connector and optional producer policy are configured; IAM propagation and service latency can still affect startup. No history before capture is recovered.

The current Oracle provider exposes custom-content ZIP import, but not individual parser/source upsert resources. The deployer calls `oci_dashboards.native_schema.install` directly through its Python SDK phase. Terraform has no `local-exec`, shell commands, installer paths or Python executable inputs. The schema phase runs only under `--apply`, after successful Terraform planning/deletion checks and before applying the reviewed plan. The namespace must be known in `planned_values.outputs.log_analytics_namespace.value`; an unresolved namespace stops setup without guessing or creating resources. The selected profile is rechecked against the planned tenancy/region and the generated schema against the configured scope before SDK writes. No environment handoff or child Python process is used.

The installer defines its own JSON parser with root `$` (header marker `$:0`) and JSON paths in `structured_column_info`, resolves the standard Time field through paginated field metadata, and reads predefined source metadata for the File source type/entity types. It makes no assumption about the type or content of Oracle's Unified Schema parser; that built-in can be non-JSON or have no content. It creates scope-qualified STRING fields for the native scalar paths, maps eventTime to the standard Time field and to a preserved native timestamp field, and upserts a dedicated JSON parser/source. Before publishing the parser/source, it calls Oracle's parser-test API with a synthetic fixture and requires extracted event ID/status. The test does not upload log data. Existing same-name custom objects must have this deployment's description and ETag; system/unowned content, permission errors, missing metadata or parser-test failure stop apply. No field/parser/source delete operation exists.

Schema upserts are owned by the Python deployer, not Terraform CRUD. Every `--apply` reconciles owned schema definitions through SDK metadata/ETag checks before Terraform apply; `--plan` performs no schema writes. Direct Terraform apply does not run this setup. A failed setup may leave owned fields; fix the cause and repeat apply with the same state. Retiring custom schema content requires separate review. Do not modify the generated schema ownership description or reuse another scope's names.

## IAM

All policies are in the tenancy root using `oci.home`, discovered from the region subscription marked `is_home_region`. No unique home record means failure. The namespace is read using the profile tenancy OCID; onboarding/tenancy ownership is checked before apply proceeds. No dynamic groups, user groups, user accounts or backup mutation policies are created.

With IAM enabled, two service policies are provisioned:

1. **Events producer:** eventrule principals in the configured source compartments may perform STREAM_READ/STREAM_PRODUCE only on the designated stream.
2. **Connector:** serviceconnector principals in the telemetry compartment may perform STREAM_READ/STREAM_CONSUME only on that stream and LOG_ANALYTICS_LOG_GROUP_UPLOAD_LOGS only on the destination analytics group.

With IAM disabled, these permissions must already exist. Exact statements are emitted as outputs/receipt. Runtime services never receive permission to inspect volumes, create/delete backups or change backup policies.

The deployment identity must already be authorized to manage the selected Events rules, stream/pool, connector, analytics log group, Management Dashboard/search imports and optional Notifications topic. It must read tenancy region subscriptions, namespace details and standard Log Analytics schema metadata, and manage custom Log Analytics fields/parsers/sources at tenancy level. When IAM creation is enabled it must manage policies at the tenancy root. This bootstrap permission cannot be granted by a deployment that lacks it. Dashboard readers need their existing dashboard/saved-search and scoped Log Analytics query permissions; the repository does not create reader group policies.

## Notifications and migration

The earlier topic option remains available: omitted/empty `alarm_destination_topic_ids` creates a scope-named topic; supplied IDs are reused. Native event activity currently creates **no alarms, subscriptions or notification-producing rules**. The topic is available for separately configured alerting. It must not be interpreted as a functioning backup-failure alert until an alert rule and confirmed subscriptions are configured.

Collector source, Functions/Dockerfiles, scheduler and checkpoint resources were removed from the repository. Previously deployed collector resources are **not** automatically removed: the identity guard refuses using a legacy output directory with this new mode. Preserve existing Terraform state and review any migration/retirement explicitly. Nothing was deployed in this session.

## Retrying the reported partial apply

The error `Oracle Unified Schema JSON parser metadata is unavailable` came from an incorrect built-in-parser assumption in the installer. That requirement is removed: the native JSON root/path definition and parser-test gate are independent of the built-in parser. The parser-test response is decoded as raw JSON through the official SDK transport because this service returns positional map arrays that the typed SDK result can discard. Both the observed positional response and documented structured entry maps are supported. Custom fields use server-assigned canonical names, resolved by owned display names on retry. The parser test still stops apply on actual field-extraction failures; no synthetic records are ingested.

`LimitExceeded` during stream creation is a separate regional partition quota failure. A new stream needs one partition; retrying cannot bypass the limit. Choose either a tenancy service-limit increase or a dedicated existing ACTIVE stream in the same profile region:

```hcl
existing_stream_id = "ocid1.stream.oc1.ap-sydney-1.YOUR_EXISTING_STREAM"
```

The existing stream is read as a Terraform data source, not imported or managed. Its actual compartment is used in producer/consumer policies. `stream_retention_hours` applies only to newly created streams. Use a dedicated stream: a shared stream's retained content is also forwarded because the connector starts at TRIM_HORIZON. No streams or their messages are deleted by this option. The separate managed stream pool is retained even with reuse so a previous failed apply's successfully created pool does not become an unintended deletion.

The new-stream resource has a moved block preserving its old state address when adding conditional reuse; a stream that was successfully created already must not be switched to another stream without reviewing the resulting deletion proposal. The deletion guard remains active. The deployment now refreshes file:// module dependencies before each plan, covering copied caches as well as linked installs such as this machine. Provider lock versions are preserved.

Keep the existing `build/native-events/` state, profile and scope. After choosing the quota remedy, rerun the same `--apply` command yourself. Do not delete state or destroy resources to retry. No retry/apply was performed by the assistant.

## Removal of local-exec

`local-exec` and the standalone environment-driven installer were removed. The schema functions now live in `src/oci_dashboards/native_schema.py`, imported by the Python deployer. The flow is `Python → reviewed Terraform plan → direct Python SDK schema setup/test → Terraform apply`. Unexpected Python exceptions retain their original messages instead of being reduced to `TypeError status=unknown` by the old installer wrapper. Moving the call does not itself fix unrelated SDK/type errors; those still stop the schema phase and prevent Terraform apply.

For compatibility with the existing failed apply, `module.central.terraform_data.native_schema` remains declared as an inert owner marker with no provisioners, triggers, dependencies on schema files, or remote side effects. Terraform may replace its tainted local marker on retry; that does not delete or recreate OCI schema objects. No manual state removal is required. Do not delete the existing state, and do not apply an older saved plan: rerun the Python entry point to generate a fresh plan and execute the schema phase in the correct order.

Python schema setup and Terraform apply are not a distributed transaction. If a later stream-quota or infrastructure error occurs, owned schema objects may already exist and will be reconciled on the next `--apply`. Existing resources/state are preserved. The existing-stream/quota remedy is unchanged.

### Parser API internal errors

An HTTP 500 `InternalError` from `upsert_parser` is an OCI service response, not a local Python type error. It does not establish whether the request was committed or whether a payload triggered a service defect. The deployer retries only this parser request for HTTP 429, 500 and 503, up to three total attempts with exponential backoff and jitter (2–3 then 4–5 seconds). Each attempt retains the identical payload, original ETag and the same OCI `opc_retry_token`; nested SDK retries are disabled. Ownership checks still run before writes. Other schema calls retain their existing no-retry behavior.

Oracle documents [retry tokens for parser upsert](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/log_analytics/client/oci.log_analytics.LogAnalyticsClient.html#oci.log_analytics.LogAnalyticsClient.upsert_parser) and [backoff for server errors](https://docs.oracle.com/en-us/iaas/Content/API/References/apierrors.htm). A final failure preserves the OCI error and request ID and prevents Terraform apply. Permission, validation, concurrency and other nonretryable errors stop immediately. No schema payload or credentials are printed by retry diagnostics.

If all three attempts fail, retain the request ID, UTC timestamp, region and operation for Oracle Support. Repeated 500s require investigation; retries do not prove the payload is accepted. Keep state and the same profile/scope. Do not bypass schema setup with direct Terraform apply. This retry handling has local fault-injection coverage; live parser upsert remains unverified by the assistant.

### Parser creation identity

New parser creation supplies the deterministic nonblank name from the generated schema (`bh_events_json_<scope hash>`). Updates retain the existing parser's internal name and ETag. Source references use the name returned by OCI. Parser lookup also checks exact display-name matches across pages and rejects ambiguous or unowned content before field writes. No additional tfvars are needed.

The live API rejected omission of `name` with HTTP 400, `Parser name cannot be blank.`, despite the SDK exposing it as optional. The omission was reverted; tests now reject blank names and verify the nonblank name in the actual SDK-serialized request. This corrects the 400 regression only. The earlier HTTP 500 remains unexplained, and live persistence is still unverified by the assistant.

### Serialized-request comparison and capture

The [parser-save investigation](parser-save-investigation.md) records the read-only comparison against three stored JSON parser definitions. The candidate request now explicitly supplies their shared default/parser settings; this is not proof of the 500's cause. The next user-run `--apply` saves `parser-upsert.request.json` and `parser-upsert.request.metadata.json` (UTC timestamp and SHA-256) in the output directory, after the test gate and before parser save. Files are private mode 0600 and remain under ignored `build/`. The body contains schema metadata and a synthetic example; credentials and signed headers are excluded. Capture failure stops before parser/source save. `--prepare` and `--plan` do not run this capture or schema setup. No new tfvars are required.

### Source `iname not exists` on repeat apply

The reported HTTP 400 from `upsert_source` included `iname not exists` and identified the expected internal name as `OCI Block Volume Backup Events <scope hash>`. GET-only inspection confirmed that this owned source already exists under that exact name, has an ETag/source ID/edit version, and references the generated backup-events parser. The old generated `bh_events_<scope hash>` identifier returns 404. The preceding parser upsert completed in the operator's run; the error is in source persistence.

The generator now uses the observed canonical source name for both schema upsert and Terraform `native_source_name` (the connector's `log_source_identifier`). Existing source ownership is checked, and its source ID/edit version/ETag are preserved. A returned source identity that differs from the planned connector identifier stops setup. Obsolete generated schema files with mismatched source/display names are rejected before writes. No schema content is deleted or renamed by this fix, and no new tfvars are needed.

Source requests are captured privately as `source-upsert.request.json` and `source-upsert.request.metadata.json` before sending, with the same body-only, mode-0600 and SHA-256 behavior as parser capture. These files are generated only in the apply-time schema phase. They contain source/parser metadata, not credentials or signed headers.

Rerun the Python entry point with the same profile, scope and existing `build/native-events/` output directory when ready to apply. It regenerates the wrapper/schema and creates a fresh plan with the corrected source identifier. Do not apply the old saved plan directly or replace/delete the existing Terraform state. Live source update and connector creation still require operator verification; local tests and read-only inspection do not deploy the change.

### Source HTTP 412 after parser save

The source ETag and edit version must be refreshed after changing its linked parser. The installer first checks source ownership and the presence of an ETag before schema writes. After parser save, it GETs the source again, revalidates ownership, canonical name and the original source ID, then builds the source request with the fresh edit version and ETag. A source that disappeared or was replaced is not silently recreated. Missing permissions or refreshed ETag stop source publication. The captured source request therefore includes the refreshed edit version/source ID.

This fixes reuse of an earlier source revision across field/parser writes. ETag protection remains enabled. A genuine concurrent change after the fresh GET can still return HTTP 412; that error stops setup without an automatic retry or unconditional overwrite. No tfvars or Terraform-state changes are required.

### Dashboard import: invalid or missing `screenImage`

The reported `ImportDashboard` HTTP 400 identified a missing/invalid dashboard `screenImage`. The generated dashboard omitted this property. The supplied WAF archive included `screen-image` as a mandatory placeholder, but the extracted dashboard shape omitted it; saved-search templates retained their separate image fields. The placeholder is reference data, not a suitable generated preview.

The generator now embeds the checked-in `dashboards/backup-activity-preview.png` as a PNG data URI in dashboard `screen-image` (CLI JSON) / `screenImage` (Terraform/API JSON). This is a static layout preview explicitly labelled as having no live data. The editable Graphviz source is `dashboards/backup-activity-preview.dot`; Graphviz is needed only to regenerate the PNG, not to deploy. The existing widget queries, layout and identifiers are unchanged.

Local generation rejects missing, blank, placeholder, invalid-base64 or incomplete PNG previews. Both checked-in JSON definitions are regenerated. Oracle documents the [screen-image property](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/management_dashboard/models/oci.management_dashboard.models.ManagementDashboard.html) and [dashboard import workflow](https://docs.oracle.com/en-us/iaas/management-dashboard/doc/export-import-dashboards.html); the live error establishes that omitting this field was rejected for this import. Embedding PNG is our generator's chosen representation, not a claim that those documentation pages specify every accepted image encoding.

Keep the current Terraform state and rerun the Python deployment entry point to regenerate a fresh dashboard file and plan when ready. No tfvars changes are required. Prior connector/rule creations remain in state; do not destroy or reset them to retry the dashboard import. No live import retry was performed by the assistant for this change.
