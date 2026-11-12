# Dashboard validation

The default activity deployment remains collector-free. Optional coverage now adds its own inventory Function and tests alongside the event pipeline and deployment regression suite.

**166 tests passed** using `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q` with OCI SDK 2.190.0. The project targets OCI SDK 2.190+. Current Oracle documentation and the downloaded current SDK/provider source tree were consulted for supported APIs. Unit checks mock profile/credential loading. A separate attempted read-only metadata inspection used the selected profile; see the apply-failure notes below.

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
- Native Events/Streaming connector contracts, absence of collector/Functions/dynamic-group resources from the activity path, with optional coverage resources isolated separately, home-provider IAM routing, and actual Terraform evaluation of unique-home selection (missing/ambiguous homes fail).

Also passed:

- Python compilation for package/scripts/tests.
- `terraform fmt -check terraform/*.tf` (excluding operator-owned ignored tfvars).
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

## Optional coverage implementation — local checks, 11 November 2026

The separate coverage feature adds tests for individual/group-member evidence, one-volume counting, policy-vs-backup distinction, target/grace/warning boundaries, expiry, malformed/future timestamps, workload/volume overrides, pagination/repeated tokens, API denials, inaccessible scopes/regions, zero-volume denominators, complete-run selection, stale data, duplicate/out-of-order uploads and volume removal. SDK-shaped group/policy fixtures and the real Log Analytics model serializer are exercised offline. Publication tests verify bounded payloads, summary-last ordering, failures and custom metric rejection. Deployment tests parse real tfvars for disabled/enabled modes and reject missing prerequisites and sub-hour schedules.

The existing activity regression tests remain in the same suite. Tracked Terraform is validated with installed Oracle provider 9.12.0 in an isolated build directory; no plan/apply or OCI API call is needed. Coverage dashboard JSON is generated offline and its PNG preview is visually checked. Docker image startup/build and service-side parsing/query execution are not claimed as tested here. No new coverage schema, Function, IAM, schedule, image push or dashboard deployment was performed; these remain operator verification steps after preparing prerequisites. See [coverage setup](coverage.md).


## OCIR/image orchestration — local checks, 12 November 2026

Twenty additional offline tests cover source-based image identity, two-state bootstrap intent, managed repository address retention, explicit reuse, private repository validation, registry/namespace derivation, Docker/Colima context/startup and credential diagnostics, digest pinning/collision checks, source edits during builds, build failure, pending-plan behavior and final plan/schema/apply ordering. Existing-image overrides bypass bootstrap/Docker. A failed publication never advances to dashboard schema or apply. Matching receipts still require an AVAILABLE remote image/digest match; no remote read is treated as a write authorization.

Both Terraform configurations are validated independently with the installed provider in isolated directories. The new bootstrap was not planned/applied against OCI. No Docker build, push, Colima startup or live API access was performed for this implementation; command execution is mocked in tests. Runtime engine/emulation, Docker credentials, repository permission and actual image startup remain operator checks.


Coverage input simplification adds two offline checks for repository placement: bootstrap and SDK discovery both follow the resolved dashboard compartment, explicit overrides win, dashboard omission falls back to telemetry, and the state identity guard requires an explicit override to retain a previous compartment. The minimal tfvars example contains only the optional enable flag and required subnet selection; advanced inputs remain supported and documented.


OCIR pagination regression: repository/image discovery now consumes the list returned by `oci.pagination.list_call_get_all_results`, rather than accessing `.items` on that flattened result. Three tests exercise the real OCI SDK paginator against real collection/response models, including empty collections and multiple pages; only the API methods are mocked. Other `.data.items` uses in schema installation are direct unaggregated API responses and remain unchanged.


Preliminary planning adds five tests for wrapper restoration on success/failure, temporary binary removal and old final-plan invalidation, deletion-guard failure before any repository apply/Docker action, preview-before-publication ordering, and a real offline Terraform plan using the built-in terraform_data resource. No OCI plan/apply was run for this change. Preview reports are labelled non-applicable JSON; final schema/apply continue to consume only the separately generated digest-based plan.


OCIR bootstrap correction: removed unsupported is_immutable assignment in the source module, keeping private visibility, existing state addresses and deletion protection. Existing digest/collision tests remain applicable. Terraform validation is an offline schema check and did not establish service support for that flag; the service error and explicit Oracle API documentation now determine the configuration. No apply was retried during the fix.


BuildKit correction: two additional tests verify missing Buildx fails during engine preflight and local image builds explicitly use Buildx with --load and linux/amd64 without pushing. Both automatic and standalone image helpers share that build path. No Function image was rebuilt/pushed or OCI apply retried during the fix.


Local tooling check: installed and registered Homebrew Buildx v0.38.2 without changing Docker credentials or engine configuration. Colima's active Docker builder reports BuildKit v0.17.3 and linux/amd64 support. No Function image build/push or OCI deployment was executed; whether the earlier missing-content error also requires targeted cache repair is not yet established.


Push diagnostics and format correction: read-only inspection found the operator's local containerd image ID was an OCI index containing the linux/amd64 runnable manifest and a provenance attestation, while OCIR's tag resolved to the runnable child. Thus comparing the index ID directly with the child config ID was not a valid mismatch diagnosis. Builds now explicitly export Docker media types with provenance disabled. Four additional tests cover classic config/containerd manifest identity matches, rejection of differing images/source labels or incomplete indexes, verified recovery after ambiguous push failure without another push, and categorized diagnostics without token/URL leakage. The actual original Docker error was not recovered from the daemon log; format compatibility is a corrective build change, not a claim that an end-to-end push was rerun successfully. No image push or OCI deployment was performed during this investigation.


Durable build/publication checkpoints add twelve offline tests for process interruption during build, failed and interrupted pushes, OCI verification failure after remote commit, receipt loss, local cache eviction, checkpoint-only remote recovery without an engine, stale/replaced local image rejection, digest drift, delayed remote visibility, read-only planning and private atomic journal storage/corruption guards. Tests restart the workflow with the same checkpoint files and mocked Docker/OCI responses, asserting completed build/push steps are not repeated. No image build/push or OCI deployment was run for this implementation.


Functions image API correction: three tests cover splitting a verified tagged reference into separate Terraform/OCI SDK image and imageDigest fields, deferring digest-only overrides until tag discovery, and rejecting tag/digest drift. The real CreateContainerImageFunctionSourceDetails model is serialized, checking the API-bound image contains a tag and no @digest suffix. This corrects the operator's HTTP 400 Invalid Image failure; Terraform schema validation alone had not validated the service's image-name syntax. No apply was retried during the fix.


Coverage query parser correction: the live service rejected unary StaleHours negation inside dateAdd and arithmetic inside a WHERE toDate argument. The generator now computes epoch-millisecond fields first and compares numeric values. Covered/warning detail filtering uses explicit literal equality comparisons instead of ambiguous IN strings. Both checked-in dashboard JSON formats were regenerated without identity changes. Read-only service checks confirmed all fifteen generated queries parse, and fresh/stale/exact-threshold/fractional-hour examples returned the expected Fresh values using temporary eval fields on an existing Activity record. No sample logs were uploaded or saved searches modified. Coverage queries returned no inventory rows during the check, so data availability/coverage counts were not established by these syntax checks.


Coverage runtime publication/logging correction (12 November 2026): read-only Audit inspection confirmed all four inventory list APIs succeeded in all three configured compartments, along with observed policy assignment reads. The Function's LogEvents upload then returned HTTP 415 UnsupportedMediaType with application/json. No Coverage application invocation log had been configured; an unrelated application's existing log was not usable. A scheduler success and success-labelled metric were insufficient evidence of collection/publication success.

The runtime now explicitly sends application/octet-stream with payloadType=JSON. A new offline test runs the real OCI SDK request construction, intercepts before transport and checks the final HTTP header, format parameter and unmodified binary JSON payload for both volume and summary uploads. Two further tests inject authentication, inventory, upload and metric exceptions, checking failure-stage/request-ID diagnostics, unchanged exception propagation, prevention of subsequent writes and absence of false completion. Success/partial-scope diagnostics preserve the run correlation and incomplete state. Existing deployment tests also verify enabled-only wrapper outputs for runtime log IDs.

Terraform now provisions a coverage-only Logging group and application invoke service log with 30-day retention, and waits for the log before scheduling. Oracle Functions logging documentation and the provider resource documentation were reviewed. All 164 tests, Python compilation, Terraform source formatting and whitespace checks passed. Provider-backed terraform validate passed in isolated build/coverage-runtime-validation/terraform using the cached provider; live Terraform state was not touched. The operator's tfvars formatting was left as supplied. No image build/push, apply, Function invocation or log upload was performed. Corrected upload acceptance, subsequent Monitoring publication and dashboard indexing still require operator deployment and a scheduled run.


Coverage numeric tile correction: the deployed tile queries returned one summary row with Value=4/100/0, while the Console's tile default displayed the count of that row (1). The generator now ends each tile with one numeric MAX measure and excludes null outputs. Eligibility filters precede aggregation; stale unknown counts use numeric freshness arithmetic. A direct MAX of an IF-derived field returned null during read-only service trials, so that form is not used. Percentages additionally require a positive denominator and a complete fresh scope.

All 36 final read-only query assertions passed: seven actual snapshot measures (4 total, 4 covered, 100 percent, other measures zero), seven each for controlled mixed fresh, stale, partial and empty-inventory scenarios, plus a missing snapshot. Query-local null fixtures use an absent summary field with numeric conversion; literal toNumber(null) is rejected by the service. These checks validate numeric outputs and single-column aggregate metadata, not a deployed UI refresh. No records were uploaded or searches saved.

All 165 local tests passed. Both generated Coverage dashboard JSON formats reproduce exactly and retain the prior dashboard and all saved-search identities. Python compilation and whitespace checks passed. The Activity dashboard and Terraform resource definitions are unchanged by this numeric correction. No plan/apply, image build/push or Function invocation was performed. Operator deployment is required to update the displayed widgets.


Approaching-deadline details: a sixteenth Coverage widget adds a warning-only summary table with absolute deadlines, hours remaining at collection and UTC collection time. The warning query retains the existing standard Time field through snapshot deduplication; converting a floating epoch to text produced scientific notation and was not a usable date. Explicit negative FIELDS projection hides internal columns without another large grouping (the service rejected a candidate with more than four grouping fields). The shared validator now takes an expected tile count, preserving the Activity default of fifteen; reference-text checking excludes validated PNG base64 to avoid random WAF byte-string matches in thumbnails.

Five final read-only query scenarios passed: actual warning rows, optional-owner/group projection with deadline ordering, stale warnings excluded, covered records excluded, and unknown records excluded. The actual two warning records each returned 3.88 hours remaining in the inspected snapshot. Values were independently compared with deadline minus RunEpoch, and formatted collection time matched RunEpoch within timestamp precision. No records were uploaded and no saved search changed.

All 166 local tests passed, including the new table's freshness/deadline contract and existing identity references. The Coverage dashboard and all fifteen prior searches retain their identities; one new search is added. Both JSON formats reproduce, the updated illustrative preview was rendered and visually checked, and Python compilation/whitespace checks passed. Inventory runtime, schema, IAM and Terraform resources are unchanged for this addition. No plan/apply, image build/push or invocation was performed.
