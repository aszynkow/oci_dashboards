# Test backup timestamp defect — 11 November 2026

The operator created manual full backup bkcptest1 in jason_grogan_sandbox, Sydney, at 13:53:45 Melbourne time (02:53:45 UTC). Its OCID ends 35runsbsovdydjpl5ii3x3fk7r6cd3xxx6ybtt4kigiuj4l22vka. Read-only tracing through tenancy-admin's security-assessment Reader confirmed AVAILABLE state and inclusion in the configured source compartments.

## Delivery succeeded

- The native createvolumebackup.end event is timestamped 13:54:21 Melbourne time (02:54:21 UTC), with additionalDetails.status=operationSucceed and the exact supplied backup OCID.
- PublishedEvents=1 and MatchedEvents=1 for the relevant rule; DeliverySucceedEvents=1 at 13:55 Melbourne time.
- The connector reports one message read from Streaming and one written to Log Analytics at 13:55.
- Log Analytics contains one record in the configured log group/source with the correct native fields. Source/target/connector error series had no nonzero points in the checked hour. No delivery-failure series was returned; absence is distinct from an explicit zero series.

The earlier zero-activity report was a pre-test snapshot. This new event establishes successful delivery for this specific test, not continuous ingestion health.

## Exact query failure

Executing intermediate stages of the deployed search showed one row through event-type/outcome classification, then zero rows after the validity predicate:

```
EventID != null and EventID != '' and EventTime != null and toDate(EventTime) <= now()
```

Although the native field displays 2026-11-11T02:54:21Z, STRING eval produces EventTime=2026-11-11t02:54:21z. The runtime date conversion returns null for this value; syntactic ParseQuery acceptance could not detect that runtime defect. Status normalization still produced Outcome=success before this filter.

A non-persistent API comparison proved toDate(EventTime) omits the parsed value, while toDate(upper(EventTime)) returns the expected epoch timestamp 1794365661000. The generator now uppercases the native timestamp when assigning EventTime, before either valid or invalid-record date checks. It retains checks for missing, unparsable and future timestamps. It does not substitute ingestion Time for missing native eventTime.

## Verification and local change

- Both checked-in CLI/API JSON definitions regenerated.
- Regression test covers timestamp normalization before date checks in all fifteen searches, retaining invalid/future checks.
- All 81 unit tests passed; offline preparation in build/event-timestamp-fix-check verified the correction in all fifteen generated searches.
- All fifteen corrected queries were executed read-only against the existing event and asserted: success count 1 for 24h and 7d; failure/copy/unknown counts 0; recent/latest rows contain the test backup OCID; daily creation table contains one success; failure history, copy trend and invalid-record searches are empty. Responses were non-partial and no API failures were recorded.
- No schema writes, saved-search updates, Terraform plan/apply, backup creation, cursor creation, IAM changes or resource deletions were performed.

Private evidence: build/test-backup-trace.json, build/test-backup-query-trace.json, build/event-date-probes.json and build/test-backup-corrected-searches.json. Diagnostic scripts remain under ignored build/ and are not deployment dependencies. No tenancy-admin source was modified.

The user must rerun the normal profile-based deploy workflow with existing state to publish the corrected JSON. No additional test backup is needed to validate this query correction: the already ingested record remains available within its activity windows. After deployment select jason_grogan_org or tenancy root with descendants as the log-group compartment; jason_grogan_sandbox is the backup source, not the telemetry log-group compartment.

The incorrect Time tile caption remains a separate display-configuration issue and was not fixed in this change. The query's actual output is numeric Events. Browser display of the redeployed query remains unverified.

References: [Oracle eval upper/toDate functions](https://docs.oracle.com/en-us/iaas/log-analytics/doc/eval.html), [Events metrics](https://docs.oracle.com/en-us/iaas/Content/Events/Reference/eventsmetrics.htm), [Connector metrics](https://docs.oracle.com/en-us/iaas/Content/connector-hub/metrics-reference.htm).

Subsequent local change: [the tile caption fix](tile-caption-fix.md) now configures the supported Events caption for all nine count tiles. Deployment remains operator-controlled.
