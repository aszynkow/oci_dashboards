"""Coverage snapshot schema and native Log Analytics saved-search dashboard."""
import base64
from copy import deepcopy
import hashlib
import json
from .management import REFERENCE, identifier, widget_scope, validate

FIELDS = ('RecordKind RecordID RunID RunEpoch ExpectedRecords Scope StaleHours '
          'VolumeOCID VolumeName CompartmentOCID Region Workload Owner Policy PolicyState GroupOCID '
          'TargetHours GraceHours Status Reason BackupOCID BackupTime BackupAgeHours ProtectionPath '
          'GroupBackupOCID Deadline Total Covered Uncovered Unknown Warning CoveredPct UncoveredPct '
          'ScopeState ErrorCount LastSuccessfulCollection').split()


def names(scope):
    token = hashlib.sha256(scope.encode()).hexdigest()[:12]
    return {'source': 'OCI Block Volume Coverage '+token, 'display': 'OCI Block Volume Coverage '+token,
            'parser': 'bh_coverage_json_'+token, 'prefix': 'BC '+token+' ', 'token': token}


def schema(scope):
    n = names(scope)
    example = {'eventTime': '2026-11-11T00:00:00Z', 'RecordID': 'SYNTHETIC-VOLUME',
               'Status': 'unknown', 'RunID': 'SYNTHETIC-RUN', 'RecordKind': 'volume'}
    return {**n, 'scope_id': scope, 'description': 'Managed by oci_dashboards coverage v1 scope='+scope,
            'fields': [{'key': k, 'name': 'bc_'+n['token']+'_'+k, 'display_name': n['prefix']+k,
                        'path': '$.'+k} for k in FIELDS], 'example': example,
            'test_values': ['SYNTHETIC-VOLUME', 'unknown', 'SYNTHETIC-RUN']}


def base(config, *, latest=True, collection_time=False):
    n = names(config['scope_id'])
    q = "'Log Source' = '"+n['source']+"' and 'Log Group' = '__BC_LOG_GROUP_ID__'"
    q += ''.join(" | eval "+k+" = '"+n['prefix']+k+"'" for k in FIELDS)
    for key in ('RunEpoch', 'ExpectedRecords', 'StaleHours', 'Total', 'Covered', 'Uncovered', 'Unknown',
                'Warning', 'CoveredPct', 'UncoveredPct', 'ErrorCount'):
        q += f' | eval {key} = toNumber({key})'
    q += ' | eval RunEpochMs = RunEpoch * 1000 | eval QueryNowMs = toNumber(now())'
    q += ' | where RunID != null and RecordID != null and RunEpoch != null and ExpectedRecords > 0 and StaleHours > 0 and RunEpochMs <= QueryNowMs'
    # Deduplicate uploads, then admit only runs with every expected record. The
    # summary is uploaded last; incomplete ingestion never becomes current.
    measures = [f'latest({k}) as {k}' for k in FIELDS if k not in ('RunID', 'RecordID')]
    if collection_time:
        measures.append('latest(Time) as CollectedAt')
    q += ' | stats '+', '.join(measures)+' by RunID, RecordID'
    q += ' | eventstats distinctcount(RecordID) as Seen by RunID | where Seen = ExpectedRecords'
    if latest:
        q += ' | eventstats max(RunEpoch) as LatestRun | where RunEpoch = LatestRun'
    # Compute the expiry numerically: the LA parser rejects unary field
    # negation inside dateAdd's amount argument. now() converts to epoch ms.
    q += ' | eval StaleAtEpochMs = (RunEpoch + StaleHours * 3600) * 1000'
    q += ' | eval Fresh = if(StaleAtEpochMs <= toNumber(now()), 0, 1)'
    return q


def tile_value_query(summary, key):
    """Return one numeric aggregate, never the count of a summary record.

    LA returns null when max() consumes an IF-derived field after STATS.
    Filter ineligible rows first; use numeric 0/1 freshness arithmetic for
    unknowns. Do not replace an absent/stale/incomplete percentage with zero.
    """
    if key == 'Unknown':
        summary += ' | eval UnknownValue = Unknown * Fresh + Total * (1 - Fresh)'
        measure = 'UnknownValue'
    else:
        measure = key
        if key != 'Total':
            summary += ' | where Fresh = 1'
        if key.endswith('Pct'):
            summary += ' and ScopeState = literal(complete) and Total > 0'
    return summary + f' | stats max({measure}) as Value | where Value != null'


def warning_details(detail):
    """Warning rows are still covered; countdown is fixed at collection time."""
    query = detail + ' | where Fresh = 1 and Status = literal(warning)'
    query += (' | eval Deadline = upper(Deadline) | eval DeadlineDate = toDate(Deadline)'
              ' | eval DeadlineEpochMs = toNumber(DeadlineDate)'
              ' | eval HoursRemainingAtCollection = (DeadlineEpochMs / 1000 - RunEpoch) / 3600'
              ' | eval CollectedAtUTC = formatDate(CollectedAt)'
              ' | sort DeadlineEpochMs, VolumeName'
              ' | eval HoursRemainingAtCollection = round(HoursRemainingAtCollection, 2)')
    displayed = {'Status', 'VolumeName', 'VolumeOCID', 'CompartmentOCID', 'Region', 'Workload',
                 'Owner', 'ProtectionPath', 'GroupOCID', 'GroupBackupOCID', 'BackupOCID', 'BackupTime',
                 'BackupAgeHours', 'Deadline', 'TargetHours', 'GraceHours', 'Policy', 'PolicyState', 'Reason'}
    # FIELDS is additive after STATS. Explicit exclusions remove internal snapshot
    # columns without another large GROUP BY (the service limits grouping fields).
    hidden = [k for k in FIELDS if k not in displayed]
    hidden += ['Seen', 'LatestRun', 'StaleAtEpochMs', 'Fresh', 'DeadlineDate',
               'DeadlineEpochMs', 'CollectedAt']
    return query + ' | fields ' + ', '.join('-' + key for key in hidden)


def definitions(config):
    q = base(config)
    summary = q+" | where RecordKind = literal(summary)"
    result = []
    for key, title, caption in [('Total','Observed block volumes','Volumes'), ('Covered','🟢 Covered volumes','Volumes'),
        ('CoveredPct','🟢 Covered percentage','Percent'), ('Uncovered','🔴 Not covered volumes','Volumes'),
        ('UncoveredPct','🔴 Not covered percentage','Percent'), ('Unknown','⚪ Unknown volumes','Volumes'),
        ('Warning','🟠 Approaching deadline','Volumes')]:
        result.append({'key': key, 'title': title, 'viz': 'tile',
                       'query': tile_value_query(summary, key), 'caption': caption})
    detail = q+" | where RecordKind = literal(volume) | eval Status = if(Fresh = 0, literal(unknown), Status) | eval Reason = if(Fresh = 0, literal('Stale inventory; recollect before interpreting coverage'), Reason)"
    cols = 'Status, VolumeName, VolumeOCID, CompartmentOCID, Region, Workload, Owner, ProtectionPath, GroupOCID, GroupBackupOCID, BackupOCID, BackupTime, BackupAgeHours, Deadline, TargetHours, GraceHours, Policy, PolicyState, Reason, RunID'
    for key,title,condition in [('covered','🟢 Covered — includes approaching deadline',"Status = literal(covered) or Status = literal(warning)"),
                                ('uncovered','🔴 Not covered — available backup missing or too old',"Status = literal(uncovered)"),
                                ('unknown','⚪ Unknown or stale — investigate collection',"Status = literal(unknown)")]:
        result.append({'key':'details-'+key,'title':title,'viz':'summary_table','query':detail+' | where '+condition+' | fields '+cols})
        if key == 'covered':
            result.append({'key':'details-warning',
                'title':'🟠 Approaching deadline — hours remaining at last collection',
                'viz':'summary_table','query':warning_details(
                    base(config, collection_time=True)+' | where RecordKind = literal(volume)')})
    result.extend([
        {'key':'health','title':'⚪ Monitoring health — incomplete scope makes totals a lower bound','viz':'summary_table',
         'query':summary+' | fields ScopeState, Fresh, Total, ErrorCount, Reason, RunEpoch, StaleHours, RunID'},
        {'key':'errors','title':'⚪ Collection errors and inaccessible scopes','viz':'summary_table',
         'query':q+" | where RecordKind = literal(error) | fields Region, CompartmentOCID, VolumeOCID, Reason, RunID"},
        {'key':'success','title':'Last fully successful collection — check freshness above','viz':'summary_table',
         'query':base(config,latest=False)+" | where RecordKind = literal(summary) and ScopeState = literal(complete) | sort -RunEpoch | head limit=1 | fields LastSuccessfulCollection, RunID"},
        {'key':'trend','title':'Coverage snapshots — 30 days; partial scopes excluded','viz':'summary_table',
         'query':base(config,latest=False)+" | where RecordKind = literal(summary) and ScopeState = literal(complete) | sort -RunEpoch | fields RunEpoch, Total, Covered, CoveredPct, Uncovered, UncoveredPct, Unknown, Warning"},
        {'key':'compartments','title':'Volume classifications by compartment and region','viz':'summary_table',
         'query':detail+' | stats count as Volumes by CompartmentOCID, Region, Status'}])
    return result


def build(config):
    shape = json.loads(REFERENCE.read_text())
    scope = config['scope_id']
    dashboard = deepcopy(shape['dashboard'])
    preview = REFERENCE.parents[0].parent/'backup-coverage-preview.png'
    dashboard.update({'compartment-id':config['dashboard_compartment_id'],
        'display-name':'OCI Block Volume Backup Coverage — '+scope,
        'dashboard-id':identifier('managementdashboard',scope,'coverage:'+config['dashboard_compartment_id']),
        'screen-image':'data:image/png;base64,'+base64.b64encode(preview.read_bytes()).decode(),
        'description':'Read-only inventory snapshots. Counts each observed block volume once, including group-member backups. Green covered, amber approaching deadline, red uncovered, grey unknown/stale. Incomplete scope excludes unlisted volumes; totals are lower bounds. Not a restore test or DR-copy assessment.',
        'freeform-tags':{'backup_coverage_scope':scope}, 'tiles':[], 'saved-searches':[],
        'ui-config':{'isFilteringEnabled':False,'isRefreshEnabled':True,'isTimeRangeEnabled':False}})
    for index, definition in enumerate(definitions(config)):
        template = deepcopy(shape['templates'][definition['viz']])
        search,tile = template['search'],template['tile']
        sid = identifier('managementsavedsearch',scope,'coverage:'+definition['key'])
        search.update({'id':sid,'compartment-id':config['dashboard_compartment_id'],
            'display-name':scope+' — Coverage — '+definition['title'],
            'description':'Latest complete-ingestion inventory run, with stale and incomplete-scope handling. '+definition['title'],
            'freeform-tags':{'backup_coverage_scope':scope}})
        search['ui-config'].update(queryString=definition['query'],scopeFilters=widget_scope(config),
            timeSelection={'timePeriod':'relative','numUnits':30,'units':'DAYS'},
            visualizationOptions={'inputTextEnabled':True,'changeLabel':definition['caption'],'hideLabel':False} if definition['viz']=='tile' else {})
        tile.update({'saved-search-id':sid,'display-name':definition['title'],'parameters-map':{}})
        if index < 7:
            tile.update(row=(index//4)*2,column=(index%4)*3,width=3,height=2)
        else:
            tile.update(row=4+(index-7)*4,column=0,width=12,height=4)
        dashboard['saved-searches'].append(search);dashboard['tiles'].append(tile)
    result={'dashboards':[dashboard]}
    validate(result, expected_tiles=16)
    return result
