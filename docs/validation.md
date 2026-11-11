# Native activity validation

The previous collector implementation and its tests were removed when the scope changed to native operation events. The current checks cover the active event pipeline, dashboard and deployment path.

**89 tests passed** using `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q` with OCI SDK 2.190.0. The project targets OCI SDK 2.190+. Current Oracle documentation and the downloaded current SDK/provider source tree were consulted for supported APIs. Unit checks mock profile/credential loading. A separate attempted read-only metadata inspection used the selected profile; see the apply-failure notes below.

Tests cover:

- Native success/failure/unknown status locations and conflicting statuses.
- Duplicate event delivery, contradictory duplicate outcomes, later successes preserving historical failures, and explicit activity windows.
- Missing identity, invalid/naive/future timestamps, unsupported begin events and empty streams remaining unverified.
- Fifteen native saved searches/tiles, complete references, non-overlapping twelve-column layout, scoped log source/group, fixed windows, ID grouping before outcome filtering, query variants and absence of collector-specific queries.
- Generated CLI/API keys against actual OCI Management Dashboard SDK models and reproducibility of checked-in JSON.
- Real SDK field/parser/source models, native scalar/time mappings, controlled schema ownership, ETag updates, 403 failures, missing metadata, field pagination/repeated-token detection and failed parser-test gating.
- Real provider-free Terraform HCL parsing, defaults, JSON tfvars, supported environment precedence, rejected deprecated/generated inputs and value-redacted errors.
- Profile/tenancy/region authority, private-field exclusion, offline preparation, identity/state guard, simulated apply receipt and apply-only cloud mutations.
- Deletion guards, with narrowly identified no-op import/local schema marker replacement exceptions.
- Native Events/Streaming connector contracts, absence of all collector/Functions/dynamic-group resources, home-provider IAM routing, and actual Terraform evaluation of unique-home selection (missing/ambiguous homes fail).

Also passed:

- Python compilation for package/scripts/tests.
- `terraform fmt -check -recursive` (which also parses HCL syntax).
- Offline preparation using the actual current tfvars with mocked public profile identifiers; generated JSON parsing and inspection.
- Synthetic native event fixture generation and offline summary. Synthetic records are not uploaded or published.

Provider-backed validation remains **blocked by environment connectivity**: `terraform init -backend=false -input=false` in `build/native-implementation-check/terraform` failed while resolving `registry.terraform.io` (DNS: no such host). No provider-backed `validate`, cloud plan/apply, parser/schema upsert, live event capture, IAM write, or dashboard import was performed. No backup API was called.

After deployment, verify actual JSON parser tests, native status placement, Time versus preserved EventTime, Log Analytics queries/field aliases, eventrule service authorization, connector delivery, retained history and native Console appearance. The installer runs Oracle's parser-test API as an apply-time gate, but local fakes cannot establish real service behavior. No ingestion-heartbeat or notification-delivery claim is made; quiet backup activity cannot establish pipeline health.

## Reported apply failure fixes

Regression checks cover a built-in Unified Schema parser with type REGEX and missing content, independent native JSON root creation, standard Time metadata lookup, optional existing-stream OCIDs and actual stream-compartment policy wiring. The local Terraform file:// install links to the repository; other installations can cache a copy. The deployer refreshes module dependencies with `terraform get -update` before init/validate/plan. A moved block preserves the previously unindexed new-stream state address. Existing pools/state are retained.

Provider-backed `terraform validate` now passed against the cached Oracle provider **9.12.1** in an isolated `build/apply-fix-validation/terraform` directory. This reused a local provider cache and lock file; it did not plan/apply or contact OCI. Provider startup required running local validation outside the restricted sandbox. This supersedes the earlier provider-validation connectivity limitation; real service authorization and parser execution remain unverified.

A first read-only metadata request was blocked in the sandbox. A subsequent approved GET-only inspection outside it confirmed that the built-in parser is JSON with null content, header_content `$:0`, and JSON paths in structured_column_info. Oracle's non-persistent parser-test API was then called with a synthetic sample and existing built-in fields: the corrected mapping/helper extracted its event ID, status and timestamp. The endpoint returned a positional map array; the SDK's typed ParserTestResult discarded it, so the repository helper now preserves/decodes the raw JSON through the official signed SDK transport. Tests cover both result shapes and canonical custom-field names on retry.

No schemas were upserted, logs ingested, streams created or apply retries performed by the assistant. The full custom field/parser/source apply remains unverified. The streaming partition quota still requires an operator-selected existing dedicated stream or a limit increase.

## Direct Python schema setup

The environment-driven installer and Terraform local-exec were removed. Tests now import the schema library directly. Additional regression tests confirm `--prepare`/`--plan` cannot invoke schema setup, schema success precedes Terraform apply, exceptions preserve their original type/message and stop apply, namespace resolution comes from the reviewed plan, and changed profile/schema scope stops SDK construction/writes. Terraform source contains no provisioners or installer/executable path variables. The legacy marker is inert and retained for partial-state compatibility.

Only local artifact generation, fake-transport tests, compilation, formatting and isolated provider validation were performed for this change. No SDK schema setup, plan/apply or live state modification was run by the assistant. Earlier non-persistent parser-test evidence remains applicable to the moved schema library.

## FieldSummary request-type regression

The live list-fields API returns LogAnalyticsFieldSummary, while parser mappings require LogAnalyticsField. The mapper now constructs the required model from shared attributes, preserving datetime values and canonical names. The fake list response now uses the actual Summary class, and parser payloads run through the real SDK BaseClient.sanitize_for_serialization boundary before the fake transport. A regression test first reproduces the exact Summary/Field TypeError, then verifies the converted payload serializes successfully. Full Field objects pass through unchanged. No live SDK writes or apply retry were run for this fix.

## Parser HTTP 500 retry handling

Fault-injection tests cover transient and persistent parser errors, identical payload/retry-token/ETag replay, bounded backoff, immediate stops for nonretryable status codes, preservation of the original OCI error/request ID, and stopping before source publication on exhaustion. All 55 tests and Python compilation passed. No live schema request, Terraform plan/apply or deployment was run for this change. The cause of the reported service 500 remains unconfirmed.

## Persistent parser 500: creation identity

GET/list-only inspection found no parser under the generated legacy name. Existing custom parsers in the namespace had internal names equal to their display names; JSON root/path metadata matched our parser format. These observations do not prove the cause of the 500. No schema writes or parser tests were performed for this investigation.

An attempted change omitted the parser name; the operator subsequently received HTTP 400, `Parser name cannot be blank.` That change was reverted. New requests now include the deterministic generated parser name, verified in the actual SDK-serialized body. The fake API rejects blank names. Source references use the canonical name returned by upsert. Subsequent runs resolve exact display names through paginated parser metadata and retrieve the ETag; legacy named parsers remain supported. Foreign ownership, duplicate matches, changing metadata, repeated page tokens and missing upsert identity stop setup. Six added regressions exercise these cases and server-assigned identity reuse. All 61 local tests, compilation and changed-file whitespace checks passed. Live creation remains unverified; the service error cannot be considered resolved yet.

## Serialized request comparison and explicit settings

See [the investigation report](parser-save-investigation.md). GET/list-only reads obtained owned field metadata and three persisted JSON parser definitions; all attempted field/parser writes and parser tests were intercepted locally during reconstruction. The original historical wire request is not available. Offline replay using cached GET metadata confirms that the candidate request adds exactly six settings and changes no existing values or mappings. No reference-parser mapping IDs or edit versions were copied.

New regression checks exercise real SDK serialization against a portable reference-settings fixture, the capture/save ordering and test gate, capture-failure stopping, mode-0600 files, exact body equality and SHA-256. All 65 tests, compilation and changed-file whitespace checks passed. No live upsert, parser test, plan/apply or support message was performed for this change. The 500 cause and successful persistence remain unverified.

## Canonical source identity regression

The operator reported source upsert HTTP 400 with `iname not exists`. GET-only metadata inspection found the owned source under `OCI Block Volume Backup Events <scope hash>`, with the expected parser, source ID, edit version and ETag. The former generated `bh_events_<scope hash>` source name returned 404. Code now uses the canonical name in schema generation and the Terraform connector identifier, preserves source update guards, validates the returned identity, and captures the serialized source request before sending.

Five new regressions cover an existing canonical source update, rejection of obsolete generated identities, foreign ownership, unexpected returned source identity and source capture ordering on HTTP 400. Offline preparation with the current tfvars and selected profile, in isolated `build/source-name-fix-check/`, confirmed the schema and connector identifiers match the observed canonical name. All 70 tests, Python compilation and changed-file whitespace checks passed. No schema upsert, parser test, Terraform plan/apply or OCI change was performed for this fix.

## Source ETag refresh after linked parser update

Regression transport now simulates parser save changing an existing source ETag and edit version. Source save enforces the new revision and raises HTTP 412 for the stale one. The installer passes by re-reading after parser save and preserving the stable source ID. Additional cases ensure disappeared/replaced/unowned sources, refreshed GET permission failures and missing ETags block source publication/capture; a genuine 412 after refresh is propagated without retry. All 73 tests, compilation and changed-file whitespace checks passed. No OCI calls, schema writes or deployment were run for this fix.

## Dashboard screenImage import regression

The operator's ImportDashboard HTTP 400 reported invalid/missing screenImage. The generator omitted the dashboard property; the original WAF reference archive contains a mandatory placeholder at that location. GET/list-only metadata inspection and official API docs were consulted; no live import was attempted. A local PNG layout preview (clearly labelled as non-live) is now embedded in both JSON formats. Its Graphviz source is included; the rendered image was visually inspected.

Two regression tests verify exact PNG bytes and CLI/API property conversion and reject absent, blank, placeholder, invalid-base64 and truncated images before deployment. All 75 tests, Python compilation, regenerated JSON reproducibility and whitespace checks passed. Offline preparation with the current tfvars/profile in isolated build/dashboard-preview-fix-check confirms the generated API body includes the preview. No schema writes, Terraform plan/apply or dashboard import were run for this fix.

## Blank widget and saved-search details correction (11 November 2026)

The scope serialization fix, expression corrections and API syntax evidence are recorded in [the UI diagnostic](dashboard-ui-diagnostic.md#implemented-locally-deployment-pending). Five regression tests cover missing/malformed filters, compartment-vs-log-group identity, Terraform placeholder binding/API conversion, parser-safe indicator/literal expressions and deduplicated daily tables. All 80 tests passed; both checked-in JSON artifacts reproduce exactly. Offline profile-based preparation succeeded in an isolated output directory. All 15 generated queries returned HTTP 200 from OCI ParseQuery, which persists no saved searches or log data. Live rendering remains unverified pending the operator's deployment. No apply was run.

## Real test event runtime validation (11 November 2026)

The manual bkcptest1 backup established delivery through Events, Streaming and Connector Hub into Log Analytics. A runtime timestamp case-folding defect excluded it from dashboard counts despite ParseQuery success. The generator now normalizes native EventTime with upper before conversion. All 81 local tests and all fifteen real, non-persistent query-result assertions passed; the corrected 24h/7d success queries return 1. See [test-event diagnosis](test-backup-timestamp-investigation.md). No deployment or cloud resource changes were performed.

## Numeric tile caption (11 November 2026)

All nine count tiles now use Oracle-verified custom-caption settings: inputTextEnabled=true, changeLabel=Events and hideLabel=false. The unsaved OCI preview displayed Events with count 1; source inspection verified the exact serialization and tile read path. All 81 tests, compilation and isolated offline artifact checks passed. No deployment or saved-search save was run. See [caption fix evidence](tile-caption-fix.md).

## Volume and volume-group completion support (11 November 2026)

All fifteen widgets now include four native completion types. Existing saved-search names/IDs were compared against the init1.00 baseline and remain identical. Five optional scalar metadata paths were added, including the captured nested group ID and srcVolumeGroupBackupId lineage. The Events rules use an explicit four-type allowlist, excluding begins and the status-less group-copy initiation event.

All 89 local tests passed. Eight additional tests exercise sanitized captured group payloads, nested metadata extraction through actual SDK models, event-vs-job counting, duplicate delivery, unknown/conflicting/future statuses, preserved failure history, excluded initiation events, operation-family filters and retained metadata after event-ID aggregation. The fixture is explicitly synthetic and contains no live identifiers or names.

Both CLI/API dashboard definitions and their PNG preview were regenerated reproducibly. Graphviz architecture/preview images were visually checked. Python compilation, Terraform formatting and git diff whitespace checks passed. Offline preparation using the existing profile/tfvars in isolated build/group-support-check verified the new fields and stable identifiers without touching deployment state.

The preceding authorized live experiment separately captured group-backup completion, group-copy initiation, two member-copy completions and whole-group copy completion. Eight non-persistent 24h/7d candidate result assertions and minimal JSON parser path tests passed against real evidence. Temporary test capture/IAM were removed. Those checks validate the event shapes and classification, not a deployed version of this new schema. Runtime parsing of the new field references requires the operator-run schema/apply workflow; no schema writes, Terraform plan/apply, backup operations or production dashboard changes were made during this implementation turn. See [volume-group support](volume-group-support.md).
