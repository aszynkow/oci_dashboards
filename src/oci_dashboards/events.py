"""Native event schema and offline reference evaluation; never calls backup APIs."""
from datetime import datetime, timezone, timedelta
import hashlib

CREATE = 'com.oraclecloud.blockvolumes.createvolumebackup.end'
COPY = 'com.oraclecloud.blockvolumes.copyvolumebackup.end'
SUPPORTED = (CREATE, COPY)
# Every field is scalar. EventID is intentionally case-sensitive in native payloads.
PATHS = {
    'EventID': '$.eventID', 'EventType': '$.eventType', 'EventTime': '$.eventTime',
    'ResourceOCID': '$.data.resourceId', 'ResourceName': '$.data.resourceName',
    'VolumeOCID': '$.data.additionalDetails.volumeId',
    'CompartmentOCID': '$.data.compartmentId', 'CompartmentName': '$.data.compartmentName',
    'StatusDetail': '$.data.additionalDetails.status', 'StatusData': '$.data.status', 'StatusRoot': '$.status',
    'SourceType': '$.data.additionalDetails.sourceType',
    'ErrorCode': '$.data.additionalDetails.errorCode',
    'ErrorMessage': '$.data.additionalDetails.errorMessage', 'Message': '$.data.additionalDetails.message',
}


def names(scope):
    token = hashlib.sha256(scope.encode()).hexdigest()[:12]
    display = 'OCI Block Volume Backup Events ' + token
    # OCI persists these custom sources with their display name as the internal
    # name. The connector must use that same canonical identifier.
    return {'source': display, 'parser': 'bh_events_json_' + token,
            'display': display,
            'field_prefix': 'bh_' + token + '_', 'label_prefix': 'BH ' + token + ' '}


def schema(scope):
    identity = names(scope)
    return {'version': 1, 'scope_id': scope, **identity,
            'description': 'Managed by oci_dashboards native-events v1 scope=' + scope,
            'fields': [{'key': key, 'name': identity['field_prefix'] + key,
                        'display_name': identity['label_prefix'] + key, 'path': path}
                       for key, path in PATHS.items()]}


def at(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Event timestamp needs a timezone')
    return result.astimezone(timezone.utc)


def normalize(event, now):
    """Offline contract oracle for sample/test fixtures, not a deployed processor."""
    data = event.get('data') if isinstance(event.get('data'), dict) else {}
    details = data.get('additionalDetails') if isinstance(data.get('additionalDetails'), dict) else {}
    values = [event.get('status'), data.get('status'), details.get('status')]
    malformed_status = any(s is not None and not isinstance(s, str) for s in values)
    statuses = {s for s in values if isinstance(s, str) and s}
    status = next(iter(statuses)) if len(statuses) == 1 and not malformed_status else None
    outcome = {'operationSucceed': 'success', 'operationFailed': 'failure'}.get(status, 'unknown')
    valid = True
    try:
        timestamp = at(event.get('eventTime'))
        valid = timestamp <= at(now)
    except (AttributeError, TypeError, ValueError):
        timestamp, valid = None, False
    identity = event.get('eventID')
    valid = valid and isinstance(identity, str) and bool(identity.strip()) and event.get('eventType') in SUPPORTED
    return {'event_id': identity.strip() if isinstance(identity, str) else None, 'event_time': event.get('eventTime'),
            'operation': 'create' if event.get('eventType') == CREATE else 'copy',
            'resource_id': data.get('resourceId'), 'volume_id': details.get('volumeId'),
            'status': status, 'outcome': outcome if valid else 'unknown', 'valid': valid}


def summarize(events, now, hours=24):
    """Count distinct native event IDs, preserving failures after later successes."""
    records = {}
    invalid = 0
    for event in events:
        item = normalize(event, now)
        if not item['valid']:
            invalid += 1
            continue
        key = item['event_id']
        if key in records:
            previous = records[key]
            outcome = item['outcome'] if previous['outcome'] == item['outcome'] else 'unknown'
            newest = item if at(item['event_time']) >= at(previous['event_time']) else previous
            item = {**newest, 'outcome': outcome}
        records[key] = item
    counts = {'success': 0, 'failure': 0, 'unknown': 0}
    for item in records.values():
        if at(now) - timedelta(hours=hours) <= at(item['event_time']) <= at(now):
            counts[item['outcome']] += 1
    return {'recorded_outcomes': counts, 'invalid_records': invalid,
            'coverage': 'unknown', 'ingestion_health': 'unverified'}
