# Dashboard developer-view diagnostic

Inspected 11 November 2026 using the user's open Chrome tab and developer tools, followed by a read-only SDK GET of the supplied dashboard. The initial inspection performed no dashboard updates, imports, deployments or browser JavaScript execution. Subsequent local implementation changes are recorded below. Diagnostic output is private under ignored `build/live-widget-scope-diagnostic.json`.

## Confirmed widget initialization failure

All 15 deployed saved searches have `uiConfig.scopeFilters` without a `filters` array. The generated shape is a keyed object containing `LogGroup` and `isGlobal`.

The current Oracle Log Analytics client invokes `fromOpaque` on the saved search's `uiConfig.scopeFilters`. Its implementation iterates `e.filters.length`. The missing array matches the observed error:

```
TypeError: Cannot read properties of undefined (reading 'length')
T.fromOpaque → getSearchFromWidget → widget component creation
```

The browser displayed widget headings with empty bodies. This is a widget initialization failure, not evidence of zero matching records. Fixing ingestion or producing more backup events will not repair the malformed widget metadata.

## Scope identifiers

The observed Oracle client defines `LogGroup` as the log-group **compartment** filter. Our keyed object supplies a Log Analytics **log-group OCID** in that slot. The corrected opaque structure needs a `filters` array, with its `LogGroup` filter referring to the configured telemetry compartment. The specific log group should be constrained through the appropriate supported log-field/query mechanism, rather than substituted for the compartment.

The supplied URL also carries `lg:<shared_demos/network compartment>,true`, while this deployment's log-group compartment is `jason_grogan_org`. That inherited global scope should be corrected in a controlled display test after fixing widget initialization. A scope mismatch can hide data but is not the cause of the missing-array exception.

## Other observed errors

- Repeated Log Analytics unhandled-exception notifications with empty error objects.
- Oracle JET/renderer errors involving null `__k` and undefined `localName`; the latter appears on widget opening/refresh paths. These do not establish a separate root cause.
- HTTP 404 for `dashboard-custom.min.css` under the current Log Analytics plugin version and for `/root.css`. They may affect styling; no causal link to the malformed filter metadata was established.
- Chrome extension errors, including `chrome-extension://invalid/` and a content-script listener failure. These were separated from the application failures rather than treated as evidence of OCI API failure.

The developer console contained hundreds of accumulated entries; they are not hundreds of distinct proven dashboard defects. No backend Log Analytics query failure was established by the console scan.

## Implemented locally; deployment pending

The generator now emits `scopeFilters.filters[]`, validates each filter's shape, uses the telemetry compartment for `LogGroup`, leaves Entity/LogSet selections empty, and supplies the deployment region. The specific log-group OCID remains a query predicate. Read-only ParseQuery checks confirmed that predicate resolves to the actual log group. Both CLI and API dashboard JSON files were regenerated.

The blank saved-search details screenshot is consistent with this initialization defect: even a search with no matching events should display its description, time period and query. The details page's own exception stack was not independently captured, so its repair still requires a user-run import and browser verification.

Separate ParseQuery checks exposed two query defects after the scope investigation:

- Raw emoji in an eval expression was rejected. Indicators now use documented `decode64` to produce the same UTF-8 markers. Post-aggregation string constants use explicit `literal(...)`; the old forms produced `Invalid field for EVAL after STATS: success`.
- Oracle rejected `timestats` after the event-ID `stats` aggregation. Daily trends now use native summary tables: deduplicate by event ID, bucket EventDate at midnight, then count by day and outcome. This preserves duplicate/conflict handling without an unsupported time-series chain. No zero-filled days are fabricated.

All 15 corrected query strings returned HTTP 200 from the non-persistent OCI ParseQuery API on 11 November 2026. Private request IDs/results are in ignored `build/generated-query-parse-check.json`; the original failing results are preserved in `build/generated-query-parse-check.before.json`. This proves syntax acceptance, not matching data or successful UI rendering.

Eighty local tests passed. Offline preparation in isolated `build/widget-scope-fix-check` verified all fifteen scope compartments and generated deployment artifacts. No schema upsert, Terraform plan/apply, dashboard import or state changes were run for this fix.

Re-import using the existing Python deployment workflow and the original state directory. Then verify saved-search details/widgets render, clear the inherited `shared_demos/network` global scope if still present, and inspect effective time windows before interpreting counts. Native-event ingestion coverage limitations remain unchanged.

References: [Oracle eval functions](https://docs.oracle.com/en-us/iaas/log-analytics/doc/eval.html), [stats](https://docs.oracle.com/en-us/iaas/log-analytics/doc/stats.html), [timestats](https://docs.oracle.com/en-us/iaas/log-analytics/doc/timestats.html), [scope URL parameters](https://docs.oracle.com/en-us/iaas/log-analytics/doc/log-explorer-url-parameters.html).
