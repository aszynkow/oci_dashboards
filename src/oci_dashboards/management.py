"""Generate OCI-native event activity dashboard JSON using reviewed WAF export shapes."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from .config import load, validate as validate_config
from .events import CREATE, COPY, names

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT/'dashboards/reference/management-widget-shapes.json'
PREVIEW = ROOT/'dashboards/backup-activity-preview.png'


def validate_screen_image(value):
    """The generated dashboard uses an embedded PNG, never a blank placeholder."""
    prefix = 'data:image/png;base64,'
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError('dashboard screen-image must be an embedded PNG preview')
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except ValueError as exc:
        raise ValueError('dashboard screen-image contains invalid base64') from exc
    if (len(raw) < 45 or not raw.startswith(b'\x89PNG\r\n\x1a\n')
            or raw[12:16] != b'IHDR'
            or not int.from_bytes(raw[16:20], 'big') or not int.from_bytes(raw[20:24], 'big')
            or raw[-12:] != b'\x00\x00\x00\x00IEND\xaeB`\x82'):
        raise ValueError('dashboard screen-image is not a complete PNG preview')


def identifier(resource, scope, key):
    digest = base64.b32encode(hashlib.sha256((scope + ':' + key).encode()).digest()).decode().lower().rstrip('=')
    return 'ocid1.' + resource + '.oc1..' + digest


def field(config, key):
    return "'" + names(config['scope_id'])['label_prefix'] + key + "'"


def base_query(config, *, valid=True):
    n = names(config['scope_id'])
    # STRING eval values are case-folded by Log Analytics. Restore ISO T/Z
    # before toDate; otherwise valid native timestamps become null and disappear.
    query = (f"'Log Source' = '{n['display']}' and 'Log Group' = '__BH_ANALYTICS_LOG_GROUP_ID__'"
             f" | eval EventID = trim({field(config, 'EventID')})"
             f" | eval EventType = {field(config, 'EventType')}"
             f" | eval EventTime = upper({field(config, 'EventTime')})"
             f" | eval DetailStatus = if({field(config, 'StatusDetail')} = '', null, {field(config, 'StatusDetail')})"
             f" | eval DataStatus = if({field(config, 'StatusData')} = '', null, {field(config, 'StatusData')})"
             f" | eval RootStatus = if({field(config, 'StatusRoot')} = '', null, {field(config, 'StatusRoot')})"
             " | eval Status = if(DetailStatus != null, DetailStatus, if(DataStatus != null, DataStatus, RootStatus))"
             " | eval ConflictingStatus = if((DetailStatus != null and DataStatus != null and DetailStatus != DataStatus) or "
             "(DetailStatus != null and RootStatus != null and DetailStatus != RootStatus) or "
             "(DataStatus != null and RootStatus != null and DataStatus != RootStatus), 1, 0)"
             " | eval Outcome = if(ConflictingStatus = 1, literal(unknown), if(Status = 'operationSucceed', literal(success), "
             "if(Status = 'operationFailed', literal(failure), literal(unknown))))"
             f" | eval Operation = if(EventType = '{CREATE}', literal('backup creation'), literal('backup copy'))"
             f" | eval Region = literal('{config['region']}')"
             f" | where EventType in ('{CREATE}', '{COPY}')")
    context = {'ResourceName': 'ResourceName', 'BackupOCID': 'ResourceOCID', 'VolumeOCID': 'VolumeOCID',
               'Compartment': 'CompartmentName', 'CompartmentOCID': 'CompartmentOCID',
               'SourceType': 'SourceType', 'ErrorCode': 'ErrorCode', 'ErrorMessage': 'ErrorMessage', 'Message': 'Message'}
    query += ''.join(f" | eval {alias} = {field(config, key)}" for alias, key in context.items())
    if valid:
        # Native parser maps eventTime to Time. Reject future/missing native time
        # explicitly, even when Log Analytics falls back to an ingestion timestamp.
        query += (" | where EventID != null and EventID != '' and EventTime != null and toDate(EventTime) <= now()"
                  " | eval EventDate = toDate(EventTime)")
        preserved = ['Time', 'EventDate', 'EventType', 'EventTime', 'Status', 'Operation', 'Region', *context]
        query += ' | stats ' + ', '.join(f'latest({name}) as {name}' for name in preserved)
        query += (", distinctcount(Outcome) as OutcomeVariants, latest(Outcome) as Outcome by EventID"
                  " | eval Outcome = if(OutcomeVariants > 1, literal(unknown), Outcome) | sort -EventDate")

    # After stats, bare quoted output strings can be resolved as field names.
    # decode64 also avoids Oracle's parser rejecting raw emoji in expressions.
    query += (' | eval Indicator = if(Outcome = literal(failure), decode64("8J+UtA=="), '
              'if(Outcome = literal(success), decode64("8J+fog=="), decode64("4pqq")))')
    return query


def widgets(config):
    base = base_query(config)
    result = []
    for days, window in [(1, '24 hours'), (7, '7 days')]:
        for operation, event_type in [('backups', CREATE), ('copies', COPY)]:
            for outcome, indicator in [('success', '🟢'), ('failure', '🔴')]:
                title = f'{indicator} Recorded {operation}: {outcome} — {window}'
                result.append({'key': f'{operation}-{outcome}-{days}d', 'title': title, 'viz': 'tile', 'days': days,
                    'query': base + f" | where EventType = '{event_type}' and Outcome = literal('{outcome}') | stats count as Events"})
    result.append({'key': 'unknown-status', 'title': '⚪ Recorded operations with unknown status — 7 days',
        'viz': 'tile', 'days': 7, 'query': base + " | where Outcome = literal(unknown) | stats count as Events"})
    details = base
    columns = 'Indicator, EventTime, Operation, Outcome, ResourceName, BackupOCID, VolumeOCID, Compartment, CompartmentOCID, Region, SourceType, ErrorCode, ErrorMessage, Message, EventID'
    result += [
        {'key': 'failure-history', 'title': '🔴 Recorded failures — later success does not erase earlier failure',
         'viz': 'summary_table', 'days': 30, 'query': details + " | where Outcome = literal(failure) | fields " + columns},
        {'key': 'recent-activity', 'title': 'Recorded backup and copy completion events — 7 days',
         'viz': 'summary_table', 'days': 7, 'query': details + ' | fields ' + columns}]
    for operation, event_type in [('Backup creation', CREATE), ('Backup copy', COPY)]:
        result.append({'key': operation + '-trend', 'title': operation + ' outcomes by day — 30 days',
            'viz': 'summary_table', 'days': 30,
            'query': base + f" | where EventType = '{event_type}' | eval Day = dateSet(EventDate, hour, 0, minute, 0, sec, 0, msec, 0) | stats count as Events by Day, Outcome | sort Day"})
    result += [
        {'key': 'invalid-records', 'title': '⚪ Invalid event identity/time or unknown/conflicting status — 30 days',
         'viz': 'summary_table', 'days': 30,
         'query': base_query(config, valid=False) + " | where EventID = null or EventID = '' or EventTime = null or toDate(EventTime) = null or toDate(EventTime) > now() or Outcome = literal(unknown) | fields Time, EventTime, EventID, EventType, DetailStatus, DataStatus, RootStatus, Outcome"},
        {'key': 'last-observed', 'title': '⚪ Latest recorded event — activity timestamp, NOT ingestion health',
         'viz': 'summary_table', 'days': 30,
         'query': details + ' | head limit=1 | fields EventTime, Operation, Outcome, BackupOCID, Region, EventID'}]
    return result


def widget_scope(config):
    """Opaque UI scope: fromOpaque consumes filters[], not keyed aliases.

    LogGroup is the compartment selector. The query separately restricts the
    actual log group by OCID. Empty Entity values impose no entity restriction.
    """
    compartment = config['telemetry_compartment_id']
    return {'isGlobal': False, 'filters': [
        {'type': 'LogGroup', 'flags': {'IncludeSubCompartments': False},
         'values': [{'label': 'Backup telemetry compartment', 'value': compartment}]},
        {'type': 'Entity', 'flags': {'IncludeDependents': False, 'ScopeCompartmentId': compartment},
         'values': []},
        {'type': 'LogSet', 'flags': {}, 'values': []},
        {'type': 'Region', 'flags': {},
         'values': [{'label': config['region'], 'value': config['region']}]}
    ]}


def validate_widget_scope(scope):
    if not isinstance(scope, dict) or not isinstance(scope.get('filters'), list):
        raise ValueError('widget scopeFilters must contain a filters array')
    filters = {}
    for item in scope['filters']:
        if (not isinstance(item, dict) or not isinstance(item.get('type'), str)
                or not isinstance(item.get('flags'), dict) or not isinstance(item.get('values'), list)):
            raise ValueError('widget scope filter requires type, flags and values')
        if item['type'] in filters:
            raise ValueError('duplicate widget scope filter type')
        for value in item['values']:
            if not isinstance(value, dict) or not isinstance(value.get('value'), str) or not value['value']:
                raise ValueError('widget scope filter values must contain nonblank identifiers')
        filters[item['type']] = item
    if any(kind not in filters for kind in ('LogGroup', 'Entity', 'LogSet', 'Region')):
        raise ValueError('widget scope requires compartment, entity, log-set and region filters')
    values = filters['LogGroup']['values']
    if len(values) != 1:
        raise ValueError('widget LogGroup scope requires one compartment identifier')
    compartment = values[0]['value']
    if compartment != '__BH_TELEMETRY_COMPARTMENT_ID__' and not re.fullmatch(r'ocid1\.(compartment|tenancy)\.[A-Za-z0-9_.-]+', compartment):
        raise ValueError('widget LogGroup scope must reference a compartment, not a log group')
    if filters['Entity']['flags'].get('ScopeCompartmentId') != compartment:
        raise ValueError('widget entity scope compartment must match the log-group compartment')
    if len(filters['Region']['values']) != 1:
        raise ValueError('widget scope requires one deployment region')
    if scope.get('isGlobal') is not False:
        raise ValueError('widget scope must explicitly use its saved local filters')


def build(config, compartment_id=None, display_name=None):
    validate_config(config)
    compartment_id = compartment_id or config['dashboard_compartment_id']
    shape = json.loads(REFERENCE.read_text())
    dashboard = deepcopy(shape['dashboard'])
    scope = config['scope_id']
    dashboard.update({'compartment-id': compartment_id,
        'display-name': (display_name or 'OCI Block Volume Backup Activity') + ' — ' + scope,
        'dashboard-id': identifier('managementdashboard', scope, compartment_id),
        'screen-image': 'data:image/png;base64,' + base64.b64encode(PREVIEW.read_bytes()).decode('ascii'),
        'description': ('Native Block Volume completion events only. 🟢 recorded operation success; 🔴 recorded failure; '
            '⚪ unknown/invalid data. Counts are observed events, not recovery coverage. No data is UNKNOWN. '
            'Latest activity is not ingestion health. History starts when event capture is enabled. '
            'No inventory, recovery-target, available-backup or destination-copy verification is performed.'),
        'freeform-tags': {'backup_activity_scope': scope}, 'tiles': [], 'saved-searches': [],
        'ui-config': {'isFilteringEnabled': False, 'isRefreshEnabled': True, 'isTimeRangeEnabled': False}})
    row = 0
    for index, definition in enumerate(widgets(config)):
        template = deepcopy(shape['templates'][definition['viz']])
        search, tile = template['search'], template['tile']
        saved_id = identifier('managementsavedsearch', scope, 'native-events:' + definition['key'])
        search.update({'compartment-id': compartment_id, 'id': saved_id,
                       'display-name': scope + ' — ' + definition['title'], 'description': definition['title'],
                       'freeform-tags': {'backup_activity_scope': scope}})
        ui = search['ui-config']
        # Oracle's tile can infer Time for this multi-stage query. Pin the
        # supported custom caption to the final Events count.
        options = ({'inputTextEnabled': True, 'changeLabel': 'Events', 'hideLabel': False}
                   if definition['viz'] == 'tile' else {})
        ui.update(queryString=definition['query'], visualizationOptions=options,
            scopeFilters=widget_scope(config),
            timeSelection={'timePeriod': 'relative', 'numUnits': definition['days'], 'units': 'DAYS'})
        tile.update({'saved-search-id': saved_id, 'display-name': definition['title'], 'parameters-map': {}})
        if index < 9:
            tile.update(row=(index // 4)*2, column=(index % 4)*3, width=3, height=2)
            row = 6
        elif index in (11, 12):
            tile.update(row=14, column=(index-11)*6, width=6, height=4)
            row = 18
        else:
            tile.update(row=row, column=0, width=12, height=4)
            row += 4
        dashboard['saved-searches'].append(search)
        dashboard['tiles'].append(tile)
    result = {'dashboards': [dashboard]}
    validate(result)
    return result


def validate(payload):
    for dashboard in payload['dashboards']:
        validate_screen_image(dashboard.get('screen-image'))
        for search in dashboard['saved-searches']:
            validate_widget_scope(search.get('ui-config', {}).get('scopeFilters'))
        searches = {item['id']: item for item in dashboard['saved-searches']}
        if len(searches) != len(dashboard['saved-searches']):
            raise ValueError('duplicate saved search reference')
        if len(dashboard['tiles']) != 15:
            raise ValueError('expected 15 native activity tiles')
        cells = set()
        for tile in dashboard['tiles']:
            if tile['saved-search-id'] not in searches:
                raise ValueError('unresolved saved search reference')
            if not 0 <= tile['column'] < 12 or tile['column'] + tile['width'] > 12:
                raise ValueError('tile exceeds 12-column layout')
            for row in range(tile['row'], tile['row']+tile['height']):
                for column in range(tile['column'], tile['column']+tile['width']):
                    if (row, column) in cells:
                        raise ValueError('overlapping tiles')
                    cells.add((row, column))
        if 'WAF' in json.dumps(payload):
            raise ValueError('reference content leaked into dashboard')


def api_payload(payload):
    def convert_model(value):
        result = {}
        for key, item in value.items():
            camel = re.sub(r'-([a-z])', lambda m: m[1].upper(), key)
            if key in ('dashboards', 'saved-searches', 'tiles'):
                item = [convert_model(child) for child in item]
            result[camel] = item
        return result
    return convert_model(payload)


def main():
    parser = argparse.ArgumentParser(description='Generate OCI native backup event activity dashboard JSON')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--api', action='store_true')
    parser.add_argument('--terraform', action='store_true', help='use deployment compartment placeholders')
    args = parser.parse_args()
    config = load(args.config)
    if args.terraform:
        config.update(dashboard_compartment_id='__BH_DASHBOARD_COMPARTMENT_ID__',
                      telemetry_compartment_id='__BH_TELEMETRY_COMPARTMENT_ID__')
    payload = build(config)
    if args.api:
        payload = api_payload(payload)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
