# Parser-save HTTP 500 investigation

Reviewed 11 November 2026. **A candidate request correction is prepared; successful live persistence has not been established.** No parser/source/field writes, parser tests, Terraform plan/apply or support messages were performed during this comparison.

## Evidence and method

The production `native_schema.install()` path was executed behind an adapter that permits only metadata GET/list calls. All field upserts were intercepted and substituted with current GET results for the already-created owned fields. The parser-test transport was bypassed locally solely to reach request construction, and parser save was intercepted before any network send. OCI SDK 2.190.0's real serializer produced the JSON request body.

This is a reconstruction from current metadata, **not a capture of the historical failed HTTP request**. The next user-run `--apply` now saves the actual serialized body immediately before parser save. Historical request headers/bodies cannot be recovered from the provided error or the sanitized Audit evidence.

Three stored definitions were read for comparison:

- `Streaming - OCI Events Parser` — an existing custom JSON parser for native event-shaped records.
- `oci_unifiedschema_logtype` — Oracle's predefined JSON parser.
- `ChrisMuirCloudGuardParser` — another existing custom JSON parser.

These are persisted reference definitions, not newly validated successful ingestion pipelines or known successful create-request captures. Their sample log contents, source associations and credentials were not collected.

The request's JSON type, UTF-8 encoding, root marker `$:0`, multiline setting and structured column mapping shape match those references. Its 16 mappings use distinct canonical fields (`time` and 15 owned custom STRING fields), unique sequences and the intended native event JSON paths. No malformed mapping or duplicate field was found in this comparison.

## Prepared change

All three references include the following request-supported properties, which our request omitted:

| Property | Earlier request | Candidate request / stored references |
| --- | --- | --- |
| `isDefault` | Omitted | `true` |
| `language` | Omitted | `en_US` |
| `logTypeTestRequestVersion` | Omitted | `0` |
| `parserSequence` | Omitted | `0` |
| `isParserWrittenOnce` | Omitted | `false` |
| `shouldTokenizeOriginalText` | Omitted | `true` |

The builder now supplies these values explicitly. An offline replay using the cached field metadata confirms that **only these six properties were added**; all previous values and mappings are identical. No reference parser IDs, mapping IDs or edit versions were copied. Parser name remains nonblank. Owned updates retain their ETag and parser edit version. No additional tfvars are needed.

The flag meanings and supported request properties are documented in Oracle's [UpsertLogAnalyticsParserDetails model](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/log_analytics/models/oci.log_analytics.models.UpsertLogAnalyticsParserDetails.html). Field-mapping properties are documented in [LogAnalyticsParserField](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/log_analytics/models/oci.log_analytics.models.LogAnalyticsParserField.html).

**Inference, not an established cause:** making stored settings explicit avoids depending on undocumented service-side defaults. Stored GET responses may contain server-added defaults, and omitted properties may be valid at creation. Therefore this comparison does not prove that any omission caused HTTP 500. The existing API error and Audit event still provide no internal exception. Copying reference mapping identities or removing the required parser name would not be justified by the evidence.

## Diagnostic artifacts

Private, ignored comparison artifacts are under `build/parser-payload-comparison/20261110T231455Z/` (directory timestamps use UTC):

- `reconstructed-request.json`: before-change request reconstructed with current field metadata.
- `reference-definitions.json`: selected reference schema metadata, excluding example logs and source associations.
- `comparison.json`: reference settings and mapping comparison.
- `candidate-request.json`: after-change request rebuilt offline using the same cached field metadata.
- `candidate-diff.json`: the exact six-property difference.

Future `--apply` runs write the following under their output directory, after the parser-test gate succeeds and before parser save:

- `parser-upsert.request.json`: actual SDK-serialized schema request body, including the synthetic example.
- `parser-upsert.request.metadata.json`: UTC capture time, operation and SHA-256 of the saved file.

These mode-0600 files contain schema metadata, not signed HTTP headers, API credentials or ingested live backup records. They remain under ignored `build/`. Capture does not execute under `--prepare` or `--plan`, and does not prove the ensuing request succeeded. A capture failure stops before parser/source save. Only the latest body is kept at these paths; retain copies outside the output directory if collecting multiple support attempts.

## Verification and next live boundary

Local tests verify the actual SDK-serialized properties against a minimal reference-settings fixture, nonblank name, nested field model types, no borrowed IDs, observer ordering, private body capture, SHA-256 consistency, unchanged ownership/ETag checks and parser/source/apply failure gates. Offline reconstruction verifies the exact six-property diff.

The user remains responsible for any subsequent live apply. If parser save still returns 500, retain the captured request files with the new full OCI request ID and UTC timestamp. Oracle Support can correlate that request with the backend exception. No support case was opened. Neither further retries nor local tests establish successful persistence.
