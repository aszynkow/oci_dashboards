"""Inventory and publication failure tests: SDK-shaped responses, no OCI calls."""
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime,timedelta,timezone
import json
import io
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import Mock,patch
from oci_dashboards.coverage import collect,evaluate,pages,metrics,current_snapshot,validate_settings
from oci_dashboards.coverage_dashboard import build,schema,base,definitions
from oci_dashboards.coverage_runtime import publish_logs,batches,log_payload,publish_metrics,run
from oci_dashboards.deploy import prepare

NOW=datetime(2026,11,11,12,tzinfo=timezone.utc)
V={'id':'v1','display_name':'data','compartment_id':'c1','lifecycle_state':'AVAILABLE','freeform_tags':{'owner':'team','workload':'critical'}}
CFG={'scope_id':'test','region':'ap-sydney-1','inventory_compartment_ids':['c1'],
     'telemetry_compartment_id':'ocid1.compartment.oc1..TEST','dashboard_compartment_id':'ocid1.compartment.oc1..TEST'}

def backup(**kwargs):
    return {'id':'b1','volume_id':'v1','lifecycle_state':'AVAILABLE','time_created':NOW-timedelta(hours=2),**kwargs}


def sdk(**values):return values


class Error(Exception):
    status=403


class Inventory:
    def __init__(self):
        self.volumes=[sdk(**V)];self.backups=[sdk(**backup())];self.calls=[];self.denied=set()
    def page(self,kind,rows,kwargs):
        self.calls.append((kind,kwargs))
        if kind in self.denied:raise Error()
        return NS(data=rows,headers={})
    def list_volumes(self,**kw):return self.page('volumes',self.volumes,kw)
    def list_volume_backups(self,**kw):return self.page('backups',self.backups,kw)
    def list_volume_groups(self,**kw):return self.page('groups',[],kw)
    def list_volume_group_backups(self,**kw):return self.page('group_backups',[],kw)
    def get_volume_backup_policy_asset_assignment(self,**kw):return self.page('assignments',[],kw)


class CoverageCalculations(unittest.TestCase):
    def test_individual_and_group_member_count_each_volume_once(self):
        client=Inventory();client.backups.append(sdk(**backup(id='member',volume_group_backup_id='gb1')))
        result=collect(lambda r:client,CFG,now=NOW)
        self.assertEqual(result[-1]['Total'],1);self.assertEqual(result[-1]['Covered'],1)
        self.assertEqual(result[-1]['CoveredPct'],100)
        self.assertEqual(result[0]['PolicyState'],'none') # manual backup can cover
        row=evaluate(V,[backup(volume_group_backup_id='gb1')],{},NOW)
        self.assertEqual(row['ProtectionPath'],'group member');self.assertEqual(row['Owner'],'team')

    def test_available_not_requests_and_expiration(self):
        for b in [backup(lifecycle_state='CREATING'),backup(expiration_time=NOW),backup(lifecycle_state='FAULTY')]:
            self.assertEqual(evaluate(V,[b],{},NOW)['Status'],'uncovered')
        self.assertEqual(evaluate(V,[],{},NOW,policy='gold')['Status'],'uncovered')

    def test_targets_grace_deadline_and_warning(self):
        settings={'default_target':{'target_hours':24,'grace_hours':2,'warning_hours':4}}
        self.assertEqual(evaluate(V,[backup(time_created=NOW-timedelta(hours=20))],settings,NOW)['Status'],'covered')
        self.assertEqual(evaluate(V,[backup(time_created=NOW-timedelta(hours=25))],settings,NOW)['Status'],'warning')
        self.assertEqual(evaluate(V,[backup(time_created=NOW-timedelta(hours=26))],settings,NOW)['Status'],'uncovered')
        self.assertEqual(evaluate(V,[backup(expiration_time=NOW+timedelta(hours=1))],{},NOW)['Status'],'warning')

    def test_workload_then_volume_target_override(self):
        settings={'workload_targets':{'critical':{'target_hours':1}},'volume_targets':{'v1':{'target_hours':6}}}
        row=evaluate(V,[backup()],settings,NOW)
        self.assertEqual(row['TargetHours'],6);self.assertEqual(row['Status'],'warning')
        with self.assertRaises(ValueError):validate_settings({'default_target':{'target_hours':-1}})

    def test_invalid_and_future_dates_unknown(self):
        for dt in [None,'bad',NOW+timedelta(hours=1),datetime(2026,11,11)]:
            self.assertEqual(evaluate(V,[backup(time_created=dt)],{},NOW)['Status'],'unknown')
        self.assertEqual(evaluate(V,[backup(expiration_time='bad')],{},NOW)['Status'],'unknown')
        old=backup(time_created=NOW-timedelta(days=3));bad=backup(id='bad',time_created='bad')
        self.assertEqual(evaluate(V,[old,bad],{},NOW)['Status'],'unknown')

    def test_permission_failures_are_unknown_and_partial_scope_has_no_percentage_metric(self):
        for denied in ['backups','groups','group_backups','assignments']:
            client=Inventory();client.denied.add(denied)
            rows=collect(lambda r:client,CFG,now=NOW)
            self.assertEqual(rows[0]['Status'],'unknown')
            self.assertEqual(rows[-1]['ScopeState'],'incomplete')
            self.assertNotIn('CoveredPct',metrics(rows))
        client=Inventory();client.denied.add('volumes')
        rows=collect(lambda r:client,CFG,now=NOW)
        self.assertEqual(rows[-1]['Total'],0);self.assertEqual(rows[-1]['ScopeState'],'incomplete')
        self.assertIsNone(rows[-1]['CoveredPct'])

    def test_multiple_regions_and_client_failure(self):
        def factory(region):
            if region=='denied':raise Error()
            return Inventory()
        rows=collect(factory,{**CFG,'coverage_regions':['ap-sydney-1','denied']},now=NOW)
        self.assertEqual(rows[-1]['Total'],1);self.assertEqual(rows[-1]['ScopeState'],'incomplete')

    def test_empty_scope_is_not_100_percent(self):
        client=Inventory();client.volumes=[]
        rows=collect(lambda r:client,CFG,now=NOW)
        self.assertEqual(rows[-1]['ScopeState'],'complete');self.assertIsNone(rows[-1]['CoveredPct'])

    def test_pagination_and_failure_discard_partial_inventory(self):
        call=Mock(side_effect=[NS(data=[1],headers={'opc-next-page':'p2'}),NS(data=[2],headers={})])
        self.assertEqual(pages(call,compartment_id='c'),[1,2]);self.assertEqual(call.call_args.kwargs['page'],'p2')
        call=Mock(side_effect=[NS(data=[1],headers={'opc-next-page':'p2'}),Error()])
        with self.assertRaises(Error):pages(call)
        call=Mock(return_value=NS(data=[],headers={'opc-next-page':'loop'}))
        with self.assertRaisesRegex(ValueError,'Repeated'):pages(call)

    def test_current_run_atomic_stale_deleted_volumes_and_out_of_order_uploads(self):
        old=collect(lambda r:Inventory(),CFG,now=NOW-timedelta(hours=1),run_id='old')
        new=collect(lambda r:Inventory(),CFG,now=NOW,run_id='new')
        self.assertEqual(current_snapshot(old+new[:-1],NOW)[0]['RunID'],'old')
        self.assertEqual(current_snapshot(new+old+new,NOW)[0]['RunID'],'new')
        stale=current_snapshot(new,NOW+timedelta(hours=2))
        self.assertEqual(stale[0]['Status'],'unknown');self.assertIsNone(stale[-1]['CoveredPct'])
        empty=Inventory();empty.volumes=[]
        newer=collect(lambda r:empty,CFG,now=NOW+timedelta(hours=1),run_id='empty')
        self.assertEqual(len(current_snapshot(new+newer,NOW+timedelta(hours=1))),1)


class CoveragePublication(unittest.TestCase):
    def test_payload_bound_and_summary_last(self):
        rows=collect(lambda r:Inventory(),CFG,now=NOW)
        client=Mock();client.upload_log_events_file.return_value.headers={'opc-request-id':'upload-request'}
        with redirect_stdout(io.StringIO()):publish_logs(client,'ns','group','test',rows)
        sent=[json.loads(x.args[2]) for x in client.upload_log_events_file.call_args_list]
        self.assertEqual(json.loads(sent[-1]['logEvents'][0]['logRecords'][0])['RecordKind'],'summary')
        self.assertEqual(sent[0]['logEvents'][0]['logSourceName'],schema('test')['source'])
        self.assertTrue(all(len(log_payload(x,'source'))<1500000 for x in batches(rows,'source')))
        with self.assertRaises(ValueError):list(batches([{'large':'x'*300}],'source',100))

    def test_failed_upload_never_publishes_summary(self):
        client=Mock();client.upload_log_events_file.side_effect=Error()
        with self.assertRaises(Error):publish_logs(client,'ns','group','test',collect(lambda r:Inventory(),CFG,now=NOW))
        self.assertEqual(client.upload_log_events_file.call_count,1)

    def test_real_sdk_upload_request_is_binary_with_json_payload_type(self):
        import oci
        client=oci.log_analytics.LogAnalyticsClient({'region':'ap-sydney-1'},
            signer=Mock(spec=oci.auth.signers.SecurityTokenSigner),
            retry_strategy=oci.retry.NoneRetryStrategy())
        response=oci.response.Response(200,{'opc-request-id':'upload-request'},None,None)
        rows=collect(lambda r:Inventory(),CFG,now=NOW)
        with patch.object(client.base_client,'request',return_value=response) as send:
            with redirect_stdout(io.StringIO()):publish_logs(client,'ns','group','test',rows)
        self.assertEqual(send.call_count,2)
        for call in send.call_args_list:
            request=call.args[0]
            self.assertEqual(request.header_params['content-type'],'application/octet-stream')
            self.assertEqual(request.query_params['payloadType'],'JSON')
            self.assertIsInstance(request.body,bytes)
            self.assertTrue(json.loads(request.body)['logEvents'][0]['logRecords'])

    def test_metric_contract_and_rejected_metrics_fail(self):
        client=Mock();client.post_metric_data.return_value=NS(data=NS(failed_metrics_count=0))
        publish_metrics(client,CFG,collect(lambda r:Inventory(),CFG,now=NOW))
        payload=client.post_metric_data.call_args.args[0]
        self.assertTrue(all(m.namespace=='backup_coverage' for m in payload.metric_data))
        client.post_metric_data.return_value.data.failed_metrics_count=1
        with self.assertRaises(RuntimeError):publish_metrics(client,CFG,collect(lambda r:Inventory(),CFG,now=NOW))

    def test_dashboard_separate_identity_and_complete_run_guards(self):
        from oci_dashboards.management import build as activity
        coverage=build(CFG)['dashboards'][0];existing=activity(CFG)['dashboards'][0]
        self.assertNotEqual(coverage['dashboard-id'],existing['dashboard-id'])
        self.assertEqual(len(coverage['tiles']),16)
        self.assertFalse({s['id'] for s in coverage['saved-searches']} & {s['id'] for s in existing['saved-searches']})
        self.assertIn('Seen = ExpectedRecords',base(CFG));self.assertIn('max(RunEpoch)',base(CFG))
        self.assertIn('StaleAtEpochMs',base(CFG))
        self.assertIn('toNumber(now())',base(CFG))
        self.assertNotIn('-StaleHours',base(CFG))

    def test_numeric_tiles_emit_explicit_measure_instead_of_summary_row_count(self):
        widgets=definitions(CFG)[:7]
        generated=build(CFG)['dashboards'][0]['saved-searches'][:7]
        self.assertEqual(len(widgets),7)
        for widget,search in zip(widgets,generated):
            with self.subTest(widget=widget['key']):
                query=search['ui-config']['queryString']
                self.assertEqual(query,widget['query'])
                self.assertRegex(query,r'\| stats max\([A-Za-z]+\) as Value \| where Value != null$')
                self.assertNotIn(' | fields Value',query)
                self.assertNotIn('stats count',query)
                self.assertNotIn('ifnull(',query) # missing data cannot become healthy zero
                self.assertIn('Seen = ExpectedRecords',query)
                if widget['key'] in ('CoveredPct','UncoveredPct'):
                    self.assertIn('where Fresh = 1 and ScopeState = literal(complete)',query)
                    self.assertIn('and Total > 0',query)
                elif widget['key'] in ('Covered','Uncovered','Warning'):
                    self.assertIn('where Fresh = 1 | stats max(',query)
                elif widget['key']=='Unknown':
                    self.assertIn('Unknown * Fresh + Total * (1 - Fresh)',query)
                self.assertEqual(search['ui-config']['visualizationType'],'tile')
                self.assertEqual(search['ui-config']['visualizationOptions']['changeLabel'],widget['caption'])

    def test_warning_table_is_additive_and_uses_fresh_snapshot_deadlines(self):
        from oci_dashboards.management import identifier
        widgets=definitions(CFG)
        warning=next(w for w in widgets if w['key']=='details-warning')
        query=warning['query']
        self.assertIn('where Fresh = 1 and Status = literal(warning)',query)
        self.assertIn('latest(Time) as CollectedAt',query)
        self.assertIn('formatDate(CollectedAt)',query)
        self.assertIn('(DeadlineEpochMs / 1000 - RunEpoch) / 3600',query)
        self.assertIn('sort DeadlineEpochMs, VolumeName',query)
        self.assertNotIn('now()',query.split('HoursRemainingAtCollection',1)[1])
        self.assertIn('-ExpectedRecords',query) # internal columns hidden
        self.assertIn('includes approaching deadline',next(w['title'] for w in widgets if w['key']=='details-covered'))
        dashboard=build(CFG)['dashboards'][0]
        ids=[s['id'] for s in dashboard['saved-searches']]
        self.assertEqual(len(ids),len(set(ids)))
        for key in ['Total','Warning','details-covered','details-uncovered','details-unknown','health']:
            self.assertIn(identifier('managementsavedsearch',CFG['scope_id'],'coverage:'+key),ids)

    def test_coverage_schema_reuses_guarded_sdk_installer(self):
        import oci
        from test_schema import FakeAnalytics
        from oci_dashboards.native_schema import install
        client=FakeAnalytics()
        definition=schema('test')
        install(client,'ns','tenancy',definition,oci.log_analytics.models)
        self.assertTrue(any(kind=='source' for kind,_,_ in client.writes))

class CoverageRuntimeDiagnostics(unittest.TestCase):
    def exercise(self, *, failed_stage=None, partial=False):
        import oci
        config={**CFG,'log_analytics_namespace':'ns','coverage_log_group_id':'group'}
        inventory=Inventory()
        if partial:inventory.denied.add('backups')
        rows=collect(lambda r:inventory,config,now=NOW,run_id='test-run')
        failure=oci.exceptions.ServiceError(415,'UnsupportedMediaType',
            {'opc-request-id':'failed-request'},'PRIVATE raw exception payload')
        output=io.StringIO()
        with patch('oci.auth.signers.get_resource_principals_signer') as signer, \
             patch('oci.core.BlockstorageClient'), \
             patch('oci.log_analytics.LogAnalyticsClient'), \
             patch('oci.monitoring.MonitoringClient'), \
             patch('oci_dashboards.coverage_runtime.collect',return_value=rows) as inventory_call, \
             patch('oci_dashboards.coverage_runtime.publish_logs') as logs, \
             patch('oci_dashboards.coverage_runtime.publish_metrics') as metric_call, \
             redirect_stdout(output):
            steps={'authentication':signer,'inventory':inventory_call,'log_upload':logs,'metrics':metric_call}
            if failed_stage:steps[failed_stage].side_effect=failure
            if failed_stage:
                with self.assertRaises(oci.exceptions.ServiceError) as raised:run(config)
                self.assertIs(raised.exception,failure)
            else:run(config)
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertNotIn('PRIVATE',output.getvalue())
        self.assertNotIn('COVERAGE_CONFIG',output.getvalue())
        return events,inventory_call,logs,metric_call

    def test_every_failure_logs_stage_and_request_id_without_false_completion(self):
        for stage in ['authentication','inventory','log_upload','metrics']:
            with self.subTest(stage=stage):
                events,inventory,logs,metrics_call=self.exercise(failed_stage=stage)
                self.assertEqual(events[-1]['event'],'coverage.failed')
                self.assertEqual(events[-1]['stage'],stage)
                self.assertEqual(events[-1]['status'],415)
                self.assertEqual(events[-1]['opc_request_id'],'failed-request')
                self.assertNotIn('coverage.completed',[e['event'] for e in events])
                if stage in ['authentication','inventory']:logs.assert_not_called()
                if stage!='metrics':metrics_call.assert_not_called()

    def test_success_correlates_collection_and_publication_and_preserves_partial_state(self):
        for partial in [False,True]:
            events,inventory,logs,metrics_call=self.exercise(partial=partial)
            self.assertEqual([e['event'] for e in events],['coverage.started',
                'coverage.inventory.started','coverage.inventory.completed',
                'coverage.upload.started','coverage.metrics.started','coverage.completed'])
            run_id=events[0]['run_id']
            self.assertTrue(all(e['run_id']==run_id for e in events))
            self.assertEqual(inventory.call_args.kwargs['run_id'],run_id)
            self.assertEqual(events[-1]['scope_state'],'incomplete' if partial else 'complete')
            logs.assert_called_once();metrics_call.assert_called_once()


class CoverageSDKModels(unittest.TestCase):
    def test_real_sdk_member_lineage_and_group_policy(self):
        import oci
        client=Inventory()
        client.volumes=[oci.core.models.Volume(**V)]
        client.backups=[oci.core.models.VolumeBackup(**backup(volume_group_backup_id='gb1'))]
        client.list_volume_groups=Mock(return_value=NS(data=[oci.core.models.VolumeGroup(id='g1',volume_ids=['v1'])],headers={}))
        client.list_volume_group_backups=Mock(return_value=NS(data=[oci.core.models.VolumeGroupBackup(id='gb1',volume_backup_ids=['b1'])],headers={}))
        def assignments(**kw):
            return NS(data=[oci.core.models.VolumeBackupPolicyAssignment(policy_id='policy1')] if kw['asset_id']=='g1' else [],headers={})
        client.get_volume_backup_policy_asset_assignment=assignments
        rows=collect(lambda r:client,CFG,now=NOW)
        self.assertEqual(rows[0]['ProtectionPath'],'group member')
        self.assertEqual(rows[0]['GroupOCID'],'g1');self.assertEqual(rows[0]['Policy'],'policy1')
        self.assertEqual(rows[0]['Status'],'covered');self.assertEqual(rows[-1]['Total'],1)

    def test_group_parent_alone_does_not_cover_volume(self):
        import oci
        client=Inventory();client.backups=[]
        client.list_volume_group_backups=Mock(return_value=NS(data=[oci.core.models.VolumeGroupBackup(id='gb1',lifecycle_state='AVAILABLE',volume_backup_ids=['missing'])],headers={}))
        rows=collect(lambda r:client,CFG,now=NOW)
        self.assertEqual(rows[0]['Status'],'uncovered')
