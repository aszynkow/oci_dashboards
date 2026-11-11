# Zero activity investigation — 11 November 2026

Read-only check at 13:42 Melbourne time (02:42 UTC), using the tenancy-admin repository's security-assessment Reader, paginated backup inventory, current dashboard/Events/connector/stream metadata, synchronous Log Analytics queries, and native Monitoring metrics. Follow-up reads verified the latest volume-group membership. No deployment, schema write, backup creation, cursor creation, policy change or deletion was performed.

## Scope and actual query results

The screenshot selects tenancy root with Subcompartments checked. The API reproduction also used tenancy root and compartment_id_in_subtree=true over the preceding seven days. The dashboard still restricts its specific Log Analytics source/group; the root selector does not create Events rules in other compartments or add inventory history.

- Target log group, grouped by any Log Source: no rows, non-partial response.
- Configured source across accessible log groups: no rows, non-partial response.
- Live saved-search query for successful backups over seven days: Events=0. Its sole output column is Events, type LONG, not Time.
- Intermediate stages before outcome filtering, event validation and event-ID aggregation also return zero.

The zero therefore originates before the dashboard query filters. It is not caused by selecting the parent compartment without descendants or by dropping ingested events through the current query's status/time checks.

## Existing backups versus captured activity

Both source rules are enabled/ACTIVE and were created at approximately 12:11:24 Melbourne time on 11 November (01:11:24 UTC). They select only createvolumebackup.end and copyvolumebackup.end in two exact Sydney compartments.

| Configured compartment | Inventory records created in preceding seven days | Relevance to current event capture |
| --- | --- | --- |
| humza_sheikh_sandbox/AIDemo | 7 block-volume backups, all AVAILABLE | Newest created 11 November 00:12:55 Melbourne time (10 November 13:12:55 UTC), before capture began. |
| jason_grogan_sandbox | 18 block-volume backup records and 9 volume-group backup records | Block backups are copies with Melbourne source-backup references. The newest two were created 11 November 12:20:20 Melbourne time and are confirmed members of one replicated volume-group backup. |

Do not add group/member counts together as distinct backup operations. The latest group's member list explicitly contains both newest block backup OCIDs and two boot backup OCIDs. Its source group and original volumes are in Melbourne. Current Sydney rules do not explicitly select volume-group backup events, and there is no captured evidence that this operation emitted matching individual-volume end events to those rules. Inventory creation timestamps are not independently verified native event-completion timestamps.

Existing available backups do not automatically become historical records in this event-only dashboard. Widening the dashboard time picker cannot recreate pre-capture events.

## Delivery observations and gaps

The connector and selected existing stream are ACTIVE, with the expected source stream and destination log group/source. During the queried preceding 24 hours:

- Connector MessagesReadFromSource and BytesReadFromSource are zero.
- Returned ErrorsAtSource, ErrorsAtTarget and ServiceConnectorHubErrors series are zero.
- Stream GetMessages requests are present, but returned throughput bytes are zero. Polling requests are not delivered backup messages.
- No MessagesWrittenToTarget series was returned; this is absent evidence, not proof of successful uploads.
- No metric streams were returned from the documented oci_cloudevents namespace in either source compartment. This does not prove zero published events or successful event delivery.

All diagnostic reads completed without recorded permission/API failures. Nevertheless, an idle connector with no observed payload does not establish end-to-end ingestion health. No stream records were consumed or cursors created.

## Display issue

The screenshot captions each numeric tile with Time. The stored query returns a numeric Events column, while visualizationOptions is empty. This is a display/value-selection mismatch requiring review of the tile's UI configuration; the caption is not an elapsed-time measurement. Exact UI selection behavior and dashboard-global versus widget-local time precedence were not independently verified in this investigation. With no records even in the broad group query, those settings do not explain the current absence of logs.

## Next steps

1. Correct the numeric tile's selected value/caption to Events using a verified OCI UI/export configuration.
2. Observe the next eligible individual-volume backup in AIDemo after capture began. Check native rule matches/delivery, stream bytes, connector messages and finally Log Analytics records in sequence. A separately authorized test backup is another option; none was created here.
3. To monitor Jason's observed workload, design capture for Melbourne and documented volume-group backup events, with corresponding parser/search classifications. Do not invent an undocumented volume-group copy event or infer destination-copy availability from a creation request.
4. Historical inventory totals or verified destination-copy coverage would require a separate read-only inventory data source, which remains excluded from this deployment.

Private evidence and request IDs: ignored build/zero-activity-diagnostic.json. Diagnostic helper scripts are also under ignored build/ and are not deployment dependencies. The investigation used the existing repository venv and Reader without changing tenancy-admin source.

References: [Oracle Events types](https://docs.oracle.com/en-us/iaas/Content/Events/Reference/eventsproducers.htm), [Events metrics](https://docs.oracle.com/en-us/iaas/Content/Events/Reference/eventsmetrics.htm), [Connector metrics](https://docs.oracle.com/en-us/iaas/Content/connector-hub/metrics-reference.htm), [Connector troubleshooting](https://docs.oracle.com/en-us/iaas/Content/connector-hub/troubleshooting.htm).

## Subsequent manual test

The operator subsequently created bkcptest1. Its event was delivered and ingested, exposing a runtime timestamp conversion defect in the saved-search query. See [the test-backup investigation and local correction](test-backup-timestamp-investigation.md). The empty-group observations above remain the earlier pre-test snapshot.
