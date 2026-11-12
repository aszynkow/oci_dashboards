"""Read-only Block Volume coverage inventory and deterministic evaluation.

No create/update/delete calls against Block Volume. Inventory is exact-scope;
boot volumes and cross-region DR requirements are deliberately not inferred.
"""
from collections import defaultdict
from datetime import datetime, timezone
import uuid
import math


def instant(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def iso(value):
    return value.isoformat().replace('+00:00', 'Z') if value else None


def pages(method, **kwargs):
    """Discard partial pages on API failure; guard repeated pagination tokens."""
    rows, seen, page = [], set(), None
    while True:
        response = method(**kwargs, **({'page': page} if page else {}))
        rows.extend(response.data)
        page = response.headers.get('opc-next-page')
        if not page:
            return rows
        if page in seen:
            raise ValueError('Repeated inventory pagination token')
        seen.add(page)


def target_for(volume, settings):
    tags = volume.get('freeform_tags') or {}
    workload = tags.get(settings.get('workload_tag', 'workload'), '')
    target = {'target_hours': 24, 'grace_hours': 0, 'warning_hours': 4}
    target.update(settings.get('default_target', {}))
    target.update(settings.get('workload_targets', {}).get(workload, {}))
    target.update(settings.get('volume_targets', {}).get(volume['id'], {}))
    return workload, target


def validate_settings(settings):
    for target in [settings.get('default_target', {}), *settings.get('workload_targets', {}).values(),
                   *settings.get('volume_targets', {}).values()]:
        for key, value in target.items():
            if key not in ('target_hours', 'grace_hours', 'warning_hours') or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Coverage targets require nonnegative numeric hours')
        if target.get('target_hours', 24) <= 0:
            raise ValueError('Coverage target_hours must be positive')
    stale = settings.get('stale_hours', 2)
    if isinstance(stale, bool) or not isinstance(stale, (int, float)) or not math.isfinite(stale) or stale <= 0:
        raise ValueError('Coverage stale_hours must be positive')
    return settings


def evaluate(volume, backups, settings, now, *, errors=(), policy=None, group_id=None):
    """Only available, unexpired member/individual backups count as evidence."""
    workload, target = target_for(volume, settings)
    row = {'VolumeOCID': volume['id'], 'VolumeName': volume.get('display_name') or volume['id'],
           'CompartmentOCID': volume['compartment_id'], 'Workload': workload,
           'Owner': (volume.get('freeform_tags') or {}).get(settings.get('owner_tag', 'owner')),
           'Policy': policy, 'PolicyState': 'unknown' if errors else ('assigned' if policy else 'none'),
           'GroupOCID': group_id, 'TargetHours': target['target_hours'], 'GraceHours': target['grace_hours'],
           'Status': 'unknown', 'Reason': '; '.join(errors), 'BackupOCID': None,
           'BackupTime': None, 'BackupAgeHours': None, 'ProtectionPath': None, 'Deadline': None}
    if errors:
        return row
    usable, malformed = [], False
    for backup in backups:
        if backup.get('volume_id') != volume['id'] or backup.get('lifecycle_state') != 'AVAILABLE':
            continue
        at = instant(backup.get('time_created'))
        expiry = instant(backup.get('expiration_time'))
        if not at or at > now or (backup.get('expiration_time') and not expiry):
            malformed = True
            continue
        if expiry and expiry <= now:
            continue
        usable.append((at, backup, expiry))
    if not usable:
        row.update(Status='unknown' if malformed else 'uncovered',
                   Reason='Invalid available-backup timestamps' if malformed else 'No available unexpired backup in configured scope')
        return row
    at, backup, expiry = max(usable, key=lambda item: item[0])
    from datetime import timedelta
    deadline = at + timedelta(hours=target['target_hours'] + target['grace_hours'])
    if expiry:
        deadline = min(deadline, expiry)
    age = (now-at).total_seconds()/3600
    row.update(BackupOCID=backup['id'], BackupTime=iso(at), BackupAgeHours=round(age, 3),
               GroupBackupOCID=backup.get('volume_group_backup_id'),
               ProtectionPath='group member' if backup.get('volume_group_backup_id') else 'individual', Deadline=iso(deadline))
    if deadline <= now:
        row.update(Status='unknown' if malformed else 'uncovered',
                   Reason='Invalid backup timestamp prevents negative coverage assessment' if malformed else 'Recovery target plus grace exceeded')
    elif (deadline-now).total_seconds()/3600 <= target['warning_hours']:
        row.update(Status='warning', Reason='Approaching recovery or expiration deadline')
    else:
        row.update(Status='covered', Reason='Available backup meets recovery target')
    return row


def collect(client_factory, config, *, now=None, run_id=None):
    """Read all configured regions/compartments. API failures are persisted as unknown."""
    import oci
    settings = validate_settings(config.get('coverage_settings', {}))
    now = now or datetime.now(timezone.utc)
    run_id = run_id or str(uuid.uuid4())
    rows, failures = [], []
    regions = config.get('coverage_regions') or [config['region']]
    if len(regions) != len(set(regions)):
        raise ValueError('Coverage regions must be unique')
    compartments = config['inventory_compartment_ids']
    for region in regions:
        try:
            client = client_factory(region)
        except Exception as exc:
            failures.append({'Region': region, 'CompartmentOCID': '*', 'Reason': 'Client initialization: '+type(exc).__name__})
            continue
        volumes, backups, groups, group_backups, region_errors = [], [], [], [], []
        for compartment in compartments:
            for method, destination in [('list_volumes', volumes), ('list_volume_backups', backups),
                                        ('list_volume_groups', groups), ('list_volume_group_backups', group_backups)]:
                try:
                    destination.extend(oci.util.to_dict(x) for x in pages(getattr(client, method), compartment_id=compartment))
                except Exception as exc:
                    message = method + ': ' + str(getattr(exc, 'status', type(exc).__name__))
                    failures.append({'Region': region, 'CompartmentOCID': compartment, 'Reason': message})
                    region_errors.append(message + ' in ' + compartment)
        # Group member backup IDs provide lineage even on older SDK payloads.
        member_groups = {bid: g['id'] for g in group_backups for bid in g.get('volume_backup_ids') or []}
        by_volume = defaultdict(list)
        for b in backups:
            b['volume_group_backup_id'] = b.get('volume_group_backup_id') or member_groups.get(b['id'])
            by_volume[b.get('volume_id')].append(b)
        membership = {vid: g['id'] for g in groups for vid in g.get('volume_ids') or []}
        policies = {}
        def assignment(asset):
            if asset not in policies:
                assignments = pages(client.get_volume_backup_policy_asset_assignment, asset_id=asset)
                policies[asset] = ', '.join(sorted({x.policy_id for x in assignments})) or None
            return policies[asset]
        for v in {v['id']: v for v in volumes if v.get('lifecycle_state') not in ('TERMINATED', 'TERMINATING')}.values():
            errors, policy = list(region_errors), None
            try:
                group = membership.get(v['id'])
                own = assignment(v['id'])
                inherited = assignment(group) if group else None
                policy = '; '.join(x for x in (own, inherited) if x) or None
            except Exception as exc:
                errors.append('Policy assignment: '+str(getattr(exc, 'status', type(exc).__name__)))
                failures.append({'Region': region, 'CompartmentOCID': v['compartment_id'], 'VolumeOCID': v['id'], 'Reason': errors[-1]})
            row = evaluate(v, by_volume[v['id']], settings, now, errors=errors, policy=policy, group_id=membership.get(v['id']))
            rows.append({**row, 'Region': region, 'RecordKind': 'volume', 'RecordID': region+':'+v['id']})
    totals = {name: sum(r['Status'] == name for r in rows) for name in ('covered', 'warning', 'uncovered', 'unknown')}
    total = len(rows)
    covered = totals['covered'] + totals['warning']
    summary = {'RecordKind': 'summary', 'RecordID': 'summary', 'Total': total, 'Covered': covered,
               'Uncovered': totals['uncovered'], 'Unknown': totals['unknown'], 'Warning': totals['warning'],
               'CoveredPct': round(covered*100/total, 2) if total else None,
               'UncoveredPct': round(totals['uncovered']*100/total, 2) if total else None,
               'ScopeState': 'incomplete' if failures else 'complete', 'ErrorCount': len(failures),
               'Reason': 'Counts exclude volumes hidden by failed inventory; see collection errors' if failures else 'All configured scopes listed',
               'LastSuccessfulCollection': iso(now) if not failures else None}
    errors = [{**f, 'RecordKind': 'error', 'RecordID': 'error:'+str(i), 'Status': 'unknown'} for i, f in enumerate(failures)]
    records = [*rows, *errors, summary]
    for r in records:
        r.update(eventTime=iso(now), RunID=run_id, RunEpoch=now.timestamp(), ExpectedRecords=len(records),
                 Scope=config['scope_id'], StaleHours=settings.get('stale_hours', 2))
    return records


def metrics(records):
    summary = records[-1]
    values = {k: summary[k] for k in ('Total', 'Covered', 'Uncovered', 'Unknown', 'Warning', 'ErrorCount')}
    values['ScopeComplete'] = int(summary['ScopeState'] == 'complete')
    # A partial scope has no defensible tenancy-wide percentage.
    if summary['ScopeState'] == 'complete' and summary['CoveredPct'] is not None:
        values['CoveredPct'] = summary['CoveredPct']
        values['UncoveredPct'] = summary['UncoveredPct']
    return values


def current_snapshot(records, now):
    """Offline inspection of the same complete-run selection used by saved searches."""
    runs = defaultdict(dict)
    for record in records:
        runs[record['RunID']][record['RecordID']] = record
    complete = [list(rows.values()) for rows in runs.values()
                if any(r['RecordKind'] == 'summary' for r in rows.values())
                and all(r['ExpectedRecords'] == len(rows) and r['StaleHours'] > 0 and r['RunEpoch'] <= now.timestamp()
                        for r in rows.values())]
    if not complete:
        return []
    selected = max(complete, key=lambda rows: rows[0]['RunEpoch'])
    result = []
    for r in selected:
        r = dict(r)
        stale = now.timestamp() - r['RunEpoch'] >= r['StaleHours']*3600
        if stale:
            if r['RecordKind'] == 'volume':
                r.update(Status='unknown', Reason='Stale inventory')
            elif r['RecordKind'] == 'summary':
                r.update(Covered=None, Uncovered=None, Warning=None, CoveredPct=None,
                         UncoveredPct=None, Unknown=r['Total'])
        result.append(r)
    return result
