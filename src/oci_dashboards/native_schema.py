"""Deployment-only Log Analytics schema setup, called directly by the Python deployer.

There is no scheduler or runtime process. Reads/upserts Log Analytics metadata;
never calls Block Volume inventory APIs. No delete operations are implemented.
"""
import json
import random
import sys
import time
import uuid

from oci.retry import NoneRetryStrategy


class NativeSchemaError(ValueError):
    pass


def maybe_get(method, *args):
    try:
        return method(*args)
    except Exception as exc:
        if getattr(exc, 'status', None) == 404:
            return None
        raise


def owned(existing, description):
    if existing and (existing.data.is_system or existing.data.description != description):
        raise NativeSchemaError('Refusing to overwrite Log Analytics content not owned by this deployment')


def condition(existing):
    if not existing:
        return {}
    etag = existing.headers.get('etag')
    if not etag:
        raise NativeSchemaError('Existing Log Analytics content has no ETag; refusing an unguarded update')
    return {'if_match': etag}


def field_catalog(client, namespace):
    page, seen, fields = None, set(), {}
    while True:
        response = client.list_fields(namespace, **({'page': page} if page else {}))
        fields.update({field.name: field for field in response.data.items})
        page = response.headers.get('opc-next-page')
        if not page:
            return list(fields.values())
        if page in seen:
            raise NativeSchemaError('Repeated Log Analytics field pagination token')
        seen.add(page)


def time_field(catalog):
    found = [field for field in catalog if field.display_name == 'Time'
             and getattr(field, 'is_system', True) is not False]
    if len(found) != 1:
        raise NativeSchemaError('Cannot uniquely resolve the Oracle-defined Time field')
    return found[0]


def resolve_parser(client, namespace, definition):
    """Find owned parsers by legacy name or exact display name, across pages."""
    legacy = maybe_get(client.get_parser, namespace, definition['parser'])
    display = definition['display'] + ' JSON'
    found = {legacy.data.name: legacy} if legacy else {}
    page, seen = None, set()
    while True:
        result = client.list_parsers(namespace, parser_display_text=display,
                                     **({'page': page} if page else {}))
        for item in result.data.items:
            if item.display_name == display and item.name not in found:
                record = maybe_get(client.get_parser, namespace, item.name)
                if not record:
                    raise NativeSchemaError('Parser metadata changed during schema preparation')
                found[item.name] = record
        page = result.headers.get('opc-next-page')
        if not page:
            break
        if page in seen:
            raise NativeSchemaError('Repeated Log Analytics parser pagination token')
        seen.add(page)
    if len(found) > 1:
        raise NativeSchemaError('Ambiguous existing parser identity; refusing to overwrite')
    existing = next(iter(found.values()), None)
    owned(existing, definition['description'])
    return existing


def parser_field_model(field, models):
    """List responses are Summary models; parser requests require Field models.

    Copy shared attributes directly so timestamps retain datetime types. Using
    util.to_dict here would stringify timestamps and bypass the SDK type check.
    """
    if isinstance(field, models.LogAnalyticsField):
        return field
    return models.LogAnalyticsField(**{
        key: getattr(field, key) for key in models.LogAnalyticsField().swagger_types
        if hasattr(field, key)
    })


def parser_test_values(client, namespace, payload):
    # This OCI endpoint currently returns an array of positional field maps. The
    # SDK's ParserTestResult model discards that shape and yields empty members.
    # Keep signing/transport in the official SDK but preserve the raw JSON body.
    response = client.base_client.call_api(
        '/namespaces/{namespaceName}/parsers/actions/test', 'POST',
        path_params={'namespaceName': namespace},
        header_params={'accept': 'application/json', 'content-type': 'application/json'},
        body=payload, response_type='str', operation_name='test_parser')
    try:
        result = json.loads(response.data) if isinstance(response.data, str) else response.data
    except (ValueError, TypeError) as exc:
        raise NativeSchemaError('Parser test returned invalid JSON') from exc
    if isinstance(result, list):
        entries = result
    elif isinstance(result, dict):
        entries = result.get('entries') or []
    else:
        entries = []
    values = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Accept the observed positional array plus the documented result maps.
        values.update(str(value) for key, value in entry.items() if str(key).isdigit())
        for key in ('fieldMap', 'fieldNameValueMap', 'fieldPositionValueMap', 'fields',
                    'field_map', 'field_name_value_map', 'field_position_value_map'):
            values.update(str(value) for value in (entry.get(key) or {}).values())
    return values


def upsert_parser(client, namespace, parser, existing):
    """Retry an identical, token-protected request; never refresh its ETag.

    A server error can arrive after a commit. OCI's retry token makes replay
    safe, while retaining the original ETag protects against concurrent edits.
    Do not turn on retries globally for other schema operations.
    """
    kwargs = {**condition(existing), 'opc_retry_token': str(uuid.uuid4()),
              'retry_strategy': NoneRetryStrategy()}
    for attempt in range(3):
        try:
            return client.upsert_parser(namespace, parser, **kwargs)
        except Exception as exc:
            if getattr(exc, 'status', None) not in (429, 500, 503) or attempt == 2:
                raise
            delay = 2 ** (attempt + 1) + random.uniform(0, 1)
            request_id = (getattr(exc, 'headers', None) or {}).get('opc-request-id', 'unavailable')
            print(f'Log Analytics parser returned HTTP {exc.status}; '
                  f'retrying the same request ({attempt + 2}/3) in {delay:.1f}s; '
                  f'OCI request ID: {request_id}', file=sys.stderr)
            time.sleep(delay)


def install(client, namespace, tenancy, definition, models, *, before_parser_upsert=None, before_source_upsert=None):
    """Define native JSON root/path mappings without assuming a built-in parser type."""
    if not definition.get('source') or definition['source'] != definition.get('display'):
        raise NativeSchemaError('Generated source name must match its display name; regenerate deployment artifacts')
    source_template = client.get_source(namespace, 'ociUnifiedSchemaLogSource', tenancy).data
    if not source_template.type_name:
        raise NativeSchemaError('Oracle source type metadata is unavailable')
    description = definition['description']
    existing_parser = resolve_parser(client, namespace, definition)
    existing_source = maybe_get(client.get_source, namespace, definition['source'], tenancy)
    owned(existing_parser, description)
    owned(existing_source, description)
    # Validate the initial update guard before any writes, but do not reuse this
    # ETag after changing fields/the parser referenced by an existing source.
    condition(existing_source)
    initial_source_id = existing_source.data.source_id if existing_source else None
    # Check all ownership before any write; never replace Oracle-defined fields.
    catalog = field_catalog(client, namespace)
    existing_fields = {}
    for field in definition['fields']:
        # New custom fields receive canonical names such as udfsNNN. Resolve
        # owned display names from the complete catalog before requesting ETags.
        matches = [item for item in catalog if item.name == field['name']
                   or item.display_name == field['display_name']]
        if len(matches) > 1:
            raise NativeSchemaError('Ambiguous existing custom field display name')
        existing = maybe_get(client.get_field, namespace, matches[0].name) if matches else None
        if matches and not existing:
            raise NativeSchemaError('Field metadata changed during schema preparation')
        owned(existing, description)
        existing_fields[field['name']] = existing
    clock_field = time_field(catalog)
    mappings = [models.LogAnalyticsParserField(
        field=parser_field_model(clock_field, models), parser_field_name=clock_field.name, storage_field_name=clock_field.name,
        structured_column_info='$.eventTime', parser_field_sequence=1)]
    for number, field in enumerate(definition['fields'], 2):
        previous = existing_fields[field['name']]
        created = client.upsert_field(namespace, models.UpsertLogAnalyticsFieldDetails(
            name=previous.data.name if previous else None, display_name=field['display_name'], data_type='STRING',
            is_multi_valued=False, description=description), **condition(previous)).data
        if not created or not created.name:
            raise NativeSchemaError('Field upsert returned no canonical field name')
        mappings.append(models.LogAnalyticsParserField(
            field=parser_field_model(created, models), parser_field_name=created.name, storage_field_name=created.name,
            structured_column_info=field['path'], parser_field_sequence=number))
    parser = models.UpsertLogAnalyticsParserDetails(
        name=existing_parser.data.name if existing_parser else definition['parser'],
        display_name=definition['display'] + ' JSON',
        description=description, type='JSON', is_system=False,
        header_content='$:0', encoding='UTF-8', parser_timezone='UTC',
        # Explicit settings shared by the three persisted JSON references read
        # during the 500 investigation. Avoid relying on service-side defaults.
        # These are supported request properties, not copied server identities.
        is_default=True, language='en_US', log_type_test_request_version=0,
        parser_sequence=0, is_parser_written_once=False,
        should_tokenize_original_text=True,
        is_single_line_content=False, field_maps=mappings,
        example_content=json.dumps(definition['example']))
    if existing_parser:
        parser.edit_version = existing_parser.data.edit_version
    # Verify the real JSON parser against a synthetic fixture, without uploading
    # it as data. A bad mapping stops apply before the connector/rules start.
    test_args = {key: getattr(parser, key) for key in models.TestParserPayloadDetails().swagger_types
                 if hasattr(parser, key) and getattr(parser, key) is not None}
    values = parser_test_values(client, namespace, models.TestParserPayloadDetails(**test_args))
    required_values = definition.get('test_values') or [definition['example']['eventID'],
        definition['example']['data']['additionalDetails']['status']]
    if any(value not in values for value in required_values):
        raise NativeSchemaError('JSON parser test did not extract required fixture values')
    if before_parser_upsert:
        before_parser_upsert(parser)
    saved_parser = upsert_parser(client, namespace, parser, existing_parser).data
    if not saved_parser or not saved_parser.name:
        raise NativeSchemaError('Parser upsert returned no canonical parser name; source was not published')
    # Saving a linked parser may invalidate the source revision read above.
    # Refresh once after parser save; never blindly retry a source HTTP 412.
    refreshed_source = maybe_get(client.get_source, namespace, definition['source'], tenancy)
    owned(refreshed_source, description)
    if existing_source and (not refreshed_source or refreshed_source.data.source_id != initial_source_id):
        raise NativeSchemaError('Source identity changed during schema setup; refusing to recreate or overwrite')
    if refreshed_source and refreshed_source.data.name != definition['source']:
        raise NativeSchemaError('Refreshed source name does not match the planned connector source')
    existing_source = refreshed_source
    source_condition = condition(existing_source)
    source = models.UpsertLogAnalyticsSourceDetails(
        name=definition['source'], display_name=definition['display'], description=description,
        type_name=source_template.type_name, is_system=False,
        entity_types=[models.LogAnalyticsSourceEntityType(entity_type=item.entity_type)
                      for item in (source_template.entity_types or [])],
        parsers=[models.LogAnalyticsParser(name=saved_parser.name)])
    if existing_source:
        source.edit_version = existing_source.data.edit_version
        source.source_id = existing_source.data.source_id
    if before_source_upsert:
        before_source_upsert(source)
    saved_source = client.upsert_source(namespace, source, **source_condition).data
    if not saved_source or saved_source.name != definition['source']:
        raise NativeSchemaError('Source upsert did not return the planned connector source name; Terraform apply was stopped')
