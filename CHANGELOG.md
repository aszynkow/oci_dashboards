# Changelog

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
