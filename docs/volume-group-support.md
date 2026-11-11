# Volume and volume-group completion events

One dashboard combines both resource kinds across all fifteen widgets, without new filters, collectors or Audit ingestion. Existing widget keys, saved-search names and generated IDs remain stable.

| Operation | Event suffix (com.oraclecloud.blockvolumes.) | Evidence |
| --- | --- | --- |
| Volume backup | createvolumebackup.end | Documented; previously live-tested |
| Volume backup copy | copyvolumebackup.end | Documented; previously live-tested, including group-member copies |
| Group backup | createvolumegroupbackup.end | Documented; live-tested 11 November 2026 |
| Whole-group backup copy | copyvolumegroupbackup.end | Directly captured in the 11 November 2026 Sydney-to-Melbourne test; absent from the catalogue inspected that day |

[Oracle event catalogue](https://docs.oracle.com/en-us/iaas/Content/Events/Reference/eventsproducers.htm). The distinction between documented support and observed runtime behavior is deliberate. No undocumented suffix is inferred from an API operation name.

The native group-copy initiation event copyvolumegroupbackup was also observed, without an outcome status. It and begin events are excluded from completion capture/queries. Only operationSucceed or operationFailed establishes a known outcome; missing, new or contradictory statuses remain unknown. Native successful group backup/copy paths were live-tested. Failure-path examples in this repository are synthetic tests, not manufactured live failures.

## Counts and details

Counts deduplicate event IDs before filtering outcomes. A two-member group copy emitted two member-copy end events plus one whole-group copy end event. That contributes three copy events. It does not represent three independent copy jobs. Later successes do not erase earlier failure event IDs. No cross-event parent/member job deduplication is attempted.

ResourceType distinguishes Volume and Volume group. Volume does not imply a directly initiated operation: group-member copies use volume events too. Event tables include the event type, resource identity, group identity and copy lineage when emitted. Empty metadata is not filled from display-name guesses or unrelated inventory.

## Verified JSON paths

| Column | Native JSON path | Observed meaning |
| --- | --- | --- |
| GroupOCID | $.data.additionalDetails.volumeGroupId.id | Group identity on group-backup completion; nested object |
| SourceGroupBackupOCID | $.data.additionalDetails.srcVolumeGroupBackupId | Source backup for group-copy completion |
| SourceVolumeBackupOCID | $.data.additionalDetails.sourceBackupId | Source backup for member/individual copy completion |
| DestinationRegion | $.data.additionalDetails.destinationRegion | Copy destination |
| BackupType | $.data.additionalDetails.backupType | FULL/INCREMENTAL where supplied |
| BackupOCID | $.data.resourceId | Source backup on the observed volume-copy event; destination backup on the observed group-copy completion |
| Region | Configured event-capture region | Not an inferred source-volume or destination region |

Minimal non-persistent OCI parser tests verified the group-ID, source-group-backup and destination-region paths. The real group completion was also parsed by the existing Log Analytics pipeline. The checked-in fixture preserves the captured structures with synthetic names, times and placeholder OCIDs; it is never uploaded by deployment as live log data.

## Upgrade and scope

Use the existing Python deployer and state directory. On apply, the existing installer creates/reuses five scope-qualified optional fields, tests and updates the owned parser/source, then applies the reviewed Terraform plan. Terraform updates existing rules to include four exact completion types and reimports the JSON dashboard. No Function, scheduler, VM, extra stream, Audit connector or dynamic group is required.

No live tfvars, compartment allowlists or regions are automatically changed. Group events require the group's compartment in inventory_compartment_ids. Member events may originate in different compartments. The profile region determines capture; configure another regional deployment when necessary. Selecting a parent/root in the dashboard does not create broader event capture. Newly indexed metadata is not automatically backfilled into older records, although event-type classification can still identify their resource kind.

Keep the existing stream/source/group, saved-search identities and build/native-events Terraform state. Preview generation and --prepare are offline. Implementation validation does not perform schema writes or apply. A later operator-run apply is required before new-field query references can run against the upgraded schema.

## Limits

This is recorded activity, not inventory, current recoverability, restore testing or continuously verified cross-region coverage. Native success is the service's reported outcome at event time. Quiet/no-data periods never establish health. Event delivery, region/compartment permissions, parsing and retention affect coverage. A global dashboard time picker can override saved widget windows; check the effective range before interpreting 24-hour and seven-day labels.
