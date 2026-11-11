# Numeric tile caption fix — 11 November 2026

The deployed dashboard displayed the correct counts (including 1 for bkcptest1) with the misleading caption Time. Opening a count tile in OCI Log Explorer showed Value=Time and Group by=EventID despite the final result table containing only Events. The saved search had empty visualizationOptions. This inspection establishes the display mismatch; the query/result count was already correct after the timestamp fix.

## Verified native settings

In an unsaved Log Explorer preview, selecting Customize Tile Label and entering Events changed the visible caption from Time to Events while the count remained 1. No Save action was used. The Console session expired before serialization could be inspected there, so the exact property mapping was verified against Oracle's publicly served current UI bundle:

[Oracle Log Analytics UI bundle, version 2026011051793901992479](https://cloud.oracle.com/plugins/loganalytics/latest/2026011051793901992479/js/bundle.js).

The native UI constants map the controls to changeLabel, inputTextEnabled and hideLabel. The saved-search serializer adds scalar options directly into uiConfig.visualizationOptions; the tile initialization code reads changeLabel and uses it as the displayed tile message. No guessed field-binding properties are introduced.

The generator now writes this configuration for all nine count tiles:

```json
"visualizationOptions": {
  "inputTextEnabled": true,
  "changeLabel": "Events",
  "hideLabel": false
}
```

This is a supported custom-caption override. It does not rewrite the query, aggregation, event filtering, ingestion or native field metadata. The six summary tables retain their existing visualization settings. It does not change the explorer's inferred Value/Group by editing controls; the final Events column remains the count result.

## Validation and deployment

- Regenerated both checked-in CLI/API dashboard JSON files.
- All 81 existing unit tests passed, including generation reproducibility and CLI/API conversion.
- Python compilation passed.
- Offline profile-based preparation succeeded in isolated build/tile-caption-fix-check. All nine captions were verified in both checked-in and prepared JSON forms, with each count query still ending in stats count as Events and all six tables retaining empty visualizationOptions.
- The OCI unsaved preview displayed Events with value 1. Rendering of the generated/re-imported settings remains pending the operator's deployment.

No schema writes, saved-search saves, dashboard imports, Terraform plan/apply, backup operations or IAM changes were performed. Existing deployment/state remains under build/native-events. Use the usual Python deploy workflow with that same state directory when ready.

Private local source/serialization evidence is under ignored build/tile-caption-investigation, including the source URL, SHA-256 and relevant source locations. The downloaded vendor bundle is diagnostic evidence only, not a runtime or deployment dependency.
