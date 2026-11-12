# Changelog

## init1.03 — 2026-11-12

Documentation-only update showcasing both deployed dashboards in README's **What the dashboards show** section.

- Added Activity and Coverage screenshots captured from the OCI Console, plus links to the deployed dashboards and full-size images.
- Explained that screenshots are dated examples, live links require existing OCI access, and the global time picker can override default windows in widget labels.
- Added screenshot provenance and capture notes under `docs/screenshots/README.md`. Browser tabs, address bar and DevTools are excluded from the page captures.
- Kept the architecture diagram at the beginning of README. Dashboard, collector, IAM and Terraform behavior are unchanged.

Validation: both screenshots were visually inspected; PNG dimensions, README image references and deployment-link parameters were checked, and Git whitespace checks passed. No resources were deployed or modified.

## init1.02 — 2026-11-12

Adds an optional, separate **Block Volume Backup Coverage** dashboard and a scheduled read-only OCI Function. The existing Activity dashboard and event ingestion remain in place. Coverage reuses the exact configured compartment list and is disabled by default.

### Changes from init1.01

| Area | init1.01 | init1.02 |
| --- | --- | --- |
| Dashboards | Activity: recorded backup/copy completion events | Adds a separate 16-widget Coverage dashboard: counts/percentages, covered/approaching/not-covered/unknown details, freshness, collection errors and snapshot history |
| Recovery evidence | Completion-event outcomes | Coverage additionally inventories AVAILABLE, unexpired individual and group-member backups; counts each observed block volume once |
| Recovery requirements | No inventory target calculation | Configurable target, grace and warning hours; workload/volume overrides; missing permissions/data remain unknown |
| Runtime | Events → Streaming → Connector Hub → Log Analytics | Optional resource-principal Function with hourly detached Resource Scheduler invocation; separate coverage source/log group and derived `backup_coverage` metrics |
| Infrastructure | Activity ingestion, IAM and dashboard import | Adds optional Function/application, exact-resource dynamic groups and policies, scheduler, coverage dashboard and 30-day invocation logging |
| Deployment | OCI profile + Python schema setup + Terraform | Adds private OCIR repository in separate Terraform state, Docker/Colima image build/push and verified tagged-image/digest deployment |
| Restart behavior | Terraform state and guarded deployment receipts | Adds durable source/scope-bound image build/publication checkpoints, verified reuse and interrupted-push recovery |
| Documentation | Activity and volume-group design | Adds Coverage setup/limitations and a one-page OCI-style architecture at the start of README, with editable SVG, catalog artwork/provenance and renderer |

### Coverage behavior

- Sixteen widgets use native Console tile/summary-table shapes. Warning volumes remain included in Covered. The amber detail table sorts by earliest deadline and shows hours remaining **at collection**, plus the UTC collection time, volume/backup identity, policy, owner where tagged and recovery requirements.
- The deadline is the earlier of backup expiration and backup creation time + target + grace. An assigned policy alone is not usable-backup evidence; a manual backup can provide coverage without a policy.
- Inventory APIs paginate across explicitly selected regions and compartments. Permission/API failures produce unknown/error records; incomplete scopes suppress percentages. Complete-ingestion guards prevent partial uploads or overlapping runs from mixing snapshots. Stale results cannot appear healthy.
- Boot volumes, restore testing and required destination-copy availability are outside Coverage's current scope. Existing historical event outcomes remain separate from inventory evidence. Selecting root/subcompartments in the UI does not expand collection scope.

### Deployment and reliability

- Minimal Coverage tfvars add the enable flag and existing Function subnet IDs. Region and tenancy come from the OCI profile; namespace, home region, OCIR hostname/repository defaults and source-versioned image tags are derived. Repository compartment defaults to the resolved dashboard compartment with an override available.
- OCIR bootstrap and infrastructure retain separate state files. `--plan` previews both stacks, using a clearly labelled preliminary infrastructure preview while the image is pending. Build/push occurs only on `--apply`; an existing-image override is supported. No Terraform local-exec provisioners are introduced.
- Buildx produces a single-platform linux/amd64 Docker-format image without default attestations. OCI image identity is verified, and Functions receives a tagged `image` plus separate `image_digest`. Durable private checkpoints retain progress across failed build/push/verification steps without silently adopting unrelated images.
- Corrected SDK pagination result handling, removed unsupported OCIR immutability configuration, and added safe push diagnostics and containerd manifest/config identity handling. Docker login credentials stay external to the repository and checkpoint files.
- Corrected Log Analytics query syntax and all seven numeric tiles: tiles return an explicit numeric measure instead of counting the summary row. Real zeros remain zero; stale/missing values and incomplete percentages remain unknown. Existing dashboard/search identities are retained, with one new warning-details saved search.
- Corrected LogEvents upload media type to `application/octet-stream` with `payloadType=JSON` after Audit identified HTTP 415. Structured Function diagnostics identify collection/publication stages and OCI request IDs, and re-raise failures. Terraform enables application invocation logging before scheduling.
- Removed the duplicate tfvars example. Updated the existing architecture PNG and retained its path, alongside the new standalone architecture SVG/PNG.

### Validation and upgrade

- **166 local tests passed**, covering coverage calculations, group-member lineage, policy vs. backup evidence, pagination/API failures, stale/incomplete snapshots, publication failures, deployment planning, image/checkpoint recovery and dashboard contracts.
- **36 read-only numeric-query assertions passed** for actual values and controlled fresh/stale/partial/empty/missing snapshots. Five read-only warning-table scenarios checked actual warning membership, independent deadline arithmetic, UTC collection time, sorting and exclusion of stale/other statuses. Query overrides did not upload records or modify saved searches.
- Python compilation, generated dashboard reproducibility, preserved prior dashboard/search identities, Terraform source formatting and isolated provider validation passed during implementation. Architecture PNGs were rendered and visually inspected. See [validation evidence](docs/validation.md).

Upgrade with the existing profile-based deployer and retain **both Terraform states and image checkpoints**. See [Coverage deployment](docs/coverage.md). Service acceptance, IAM propagation, ingestion and Console rendering remain operator deployment checks; local tests do not prove a new deployment is healthy. Preparing this release does not deploy resources, invoke Functions or modify backups/policies. This is a local Git release; no remote push is performed.

## init1.01 — 2026-11-11

Extends init1.00's volume backup activity dashboard to include volume-group backup and copy completion events in the same dashboard.

### Changes from init1.00

| Area | init1.00 | init1.01 |
| --- | --- | --- |
| Event capture | Individual-volume backup and copy completions | Adds group-backup and whole-group-copy completions to the existing Terraform Events rules |
| Dashboard scope | Volume events | Combined volume and volume-group events across all 15 widgets, with existing widget keys, saved-search names and generated IDs retained |
| Event details | Volume and backup identity, outcome and error context | Adds resource type, nested group identity, source group/member backup identity, destination region, backup type and event type where emitted |
| Counting | Distinct completion event IDs | Same rule across both resource kinds; group and member-copy completion events count separately |
| Examples and tests | Volume-only synthetic examples; 81 tests | Adds sanitized synthetic group-event fixtures and examples; 89 tests |
| Documentation and previews | Volume activity design | Combined design, verified JSON paths, upgrade instructions, scope requirements and explicit event-counting limitations |

The new completion types are `com.oraclecloud.blockvolumes.createvolumegroupbackup.end` and `com.oraclecloud.blockvolumes.copyvolumegroupbackup.end`. The group-copy completion was captured in a controlled Sydney-to-Melbourne live test on 11 November 2026; it was absent from the Oracle event catalogue inspected that day. Begin events and the statusless group-copy initiation event remain excluded. See [volume-group support and evidence](docs/volume-group-support.md).

A two-member group copy can contribute **three copy events**: two member completions and one whole-group completion. These are recorded events, not three independent jobs or a count of recoverable volumes. Resource type distinguishes Volume and Volume group; a Volume event can belong to a group operation.

### Upgrade and limitations

Use the existing Python deployer, OCI profile and Terraform state. Apply installs five additional optional Log Analytics fields, updates the parser/source, expands existing capture rules and imports the generated dashboard JSON. Add required source compartments explicitly to `inventory_compartment_ids`, retaining existing entries. Selecting root/subcompartments in the dashboard does not expand capture or backfill old backups.

No collector, Function, scheduler or additional ingestion service is introduced. Missing/conflicting outcomes remain unknown, event-ID deduplication remains in place, and later successes do not erase earlier failures. A global dashboard time selection can override saved 24-hour/seven-day defaults; this release documents that limitation rather than fixing it. Inventory, recovery-target compliance and current destination-copy availability are not calculated by this event dashboard.

### Validation

- 89 local unit tests passed, including group metadata extraction, duplicate delivery, unknown/conflicting outcomes, failure history and combined widget queries.
- Python compilation, Terraform formatting and Git whitespace checks passed.
- Dashboard artifacts were generated offline and generated dashboard/saved-search identities were compared with init1.00.
- Successful native group backup/copy payloads were checked in the earlier authorized live test; failure-path fixtures are synthetic. New code and generated artifacts still require operator deployment and runtime verification.

## init1.00 — initial local baseline

Initial local commit: `d154db0` (`init1.00`). Provides the collector-free OCI Block Volume Backup Activity dashboard, generated CLI/API dashboard JSON, Terraform Events → Streaming → Service Connector → Log Analytics ingestion, profile-based Python deployment and Log Analytics schema setup. Includes event-ID deduplication, conservative outcome handling, failure history, synthetic examples and 81 local tests.
