# Native event activity definitions

There are no custom backup metrics or recovery coverage calculations in this version. Native Log Analytics saved searches read recorded Block Volume completion events.

| Display | Definition |
| --- | --- |
| Recorded backup success/failure, 24h / 7d | Distinct native eventID for createvolumebackup.end or createvolumegroupbackup.end with known status in the rolling window. |
| Recorded copy success/failure, 24h / 7d | Distinct eventID for copyvolumebackup.end or copyvolumegroupbackup.end with known status in the rolling window. |
| Unknown recorded operations | Missing/new/conflicting status, including contradictory outcomes delivered under one event ID. |
| Daily outcomes | Deduplicated events grouped by native event timestamp and reported outcome, over thirty days. |
| Failure history | Distinct failed event IDs over thirty days; later successes have separate IDs and do not erase failures. |
| Latest observed event | Most recent retained native event timestamp. It does not establish ingestion health. |
| Invalid records | Missing ID/time, parseable future time or missing/new/conflicting statuses, where ingested and identifiable as the selected event types. |

The native resource may be a backup OCID, not a volume OCID. Volume identifiers, names, errors, source type and compartment names are displayed only where emitted. No owner, policy, retention, usable-backup state or copy lineage is invented. The JSON parser preserves the exact eventID capitalization and native scalar fields. It maps eventTime to the Oracle-defined Time field. Query-time checks reject missing/future native timestamps from success/failure counts.

Status lookup accepts data.additionalDetails.status, data.status or a root status, preserving all three for diagnostics. Only operationSucceed means recorded success and only operationFailed means recorded failure; absent/unrecognized/conflicting values remain unknown. An end event without status is not counted as success.

The source compartment allowlist and deployment region establish capture scope, not a complete inventory. Events outside that scope, events lost before capture or during failures beyond retention, unparseable records and dropped deliveries are not reconstructible. Empty counts are observed activity, never proof of health. Thirty days of trend/history require thirty days of retained Log Analytics data after capture begins. Source stream buffering defaults to seven days and does not provide thirty-day analytics retention itself.

Connector delivery is at least once, so deduplicate event IDs before counting/filtering outcomes. A quiet period does not prove failure or successful ingestion. Independently inspect Events delivery, stream/connector status, Log Analytics parsing/unprocessed logs and service metrics. This version creates no ingestion-heartbeat alarm.

Native timestamp query normalization: STRING eval may case-fold the ISO timestamp to lowercase t/z. The generator applies upper to the preserved native EventTime before toDate, while retaining missing/invalid/future timestamp rejection. This prevents a valid ingested completion event from disappearing from counts. See [the real test-event verification](test-backup-timestamp-investigation.md).

## Combined resource kinds

All fifteen widgets include the four completion types. ResourceType is derived from the event type: Volume or Volume group. A Volume event can be a group member; initiation method is not inferred. Group and member copy completions count independently as distinct events, not independent jobs. One group copy with two block-volume members can contribute three successful copy events. API request/Audit success and native begin/initiation events never substitute for completion outcomes.

Optional metadata is parsed using verified paths: GroupOCID from data.additionalDetails.volumeGroupId.id, SourceGroupBackupOCID from srcVolumeGroupBackupId, SourceVolumeBackupOCID from sourceBackupId, DestinationRegion from destinationRegion, and BackupType from backupType (the last four under data.additionalDetails). Missing metadata remains blank/unknown. Region is the event capture region, not proof of the source volume region; the group-copy resource OCID can identify a destination-region backup. A success event is historical reported completion, not a continuous check of destination availability.

Time-window limitation: saved widget defaults are 24 hours / 7 days / 30 days, but a Console global time range can override them. Read the effective dashboard time picker before comparing counters.
