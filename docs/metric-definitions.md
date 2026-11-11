# Native event activity definitions

There are no custom backup metrics or recovery coverage calculations in this version. Native Log Analytics saved searches read recorded Block Volume completion events.

| Display | Definition |
| --- | --- |
| Recorded backup success/failure, 24h / 7d | Distinct native eventID for createvolumebackup.end with known status in the rolling window. |
| Recorded copy success/failure, 24h / 7d | Distinct eventID for copyvolumebackup.end with known status in the rolling window. |
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
