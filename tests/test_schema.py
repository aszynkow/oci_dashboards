"""Native schema SDK boundary tests. No OCI clients/config files are opened."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import oci
from oci_dashboards.deploy import ROOT, example_event
from oci_dashboards.events import schema, PATHS

from oci_dashboards import native_schema as installer


class APIError(Exception):
    def __init__(self,status): self.status=status


def response(data,**headers):
    return NS(data=data,headers={'etag':'etag',**headers})


class FakeAnalytics:
    def __init__(self):
        self.writes=[]
        self.objects={}
        self.denied=False
        self.fail_test=False
        self.field_pages={None:response(NS(items=[oci.log_analytics.models.LogAnalyticsFieldSummary(name='time',display_name='Time',data_type='TIMESTAMP',is_system=True)]))}
        self.base_client=self
        self.raw_test_result=None
        self.canonical_fields=False
        self.template=NS(type='REGEX',content=None,field_maps=[])
        self.parser_reads=[]
    def read(self,kind,name):
        if self.denied: raise APIError(403)
        if (kind,name) not in self.objects: raise APIError(404)
        return response(self.objects[kind,name])
    def get_parser(self,namespace,name):
        self.parser_reads.append(name)
        if name=='oci_unifiedschema_logtype': return response(self.template)
        return self.read('parser',name)
    def get_source(self,namespace,name,compartment):
        if name=='ociUnifiedSchemaLogSource': return response(NS(type_name='os_file',entity_types=[]))
        return self.read('source',name)
    def get_field(self,namespace,name): return self.read('field',name)
    def write(self,kind,payload,kwargs):
        self.writes.append((kind,payload,kwargs))
        attrs={name:getattr(payload,name) for name in payload.swagger_types}
        record=oci.log_analytics.models.LogAnalyticsField(**attrs) if kind=='field' else NS(**attrs)
        if kind=='field' and (not payload.name or (self.canonical_fields and not payload.name.startswith('udfs'))):
            record.name='udfs'+str(len(self.objects)+1)
        if kind=='parser' and (not payload.name or not payload.name.strip()):
            raise ValueError('Parser name cannot be blank.')
        if kind=='source' and payload.name!=payload.display_name:
            raise ValueError('iname not exists; source internal name must match canonical display name')
        record.is_system=False
        record.edit_version=2
        record.source_id=123
        self.objects[kind,record.name]=record
        return response(record)
    def upsert_field(self,namespace,payload,**kwargs): return self.write('field',payload,kwargs)
    def upsert_parser(self,namespace,payload,**kwargs): return self.write('parser',payload,kwargs)
    def upsert_source(self,namespace,payload,**kwargs): return self.write('source',payload,kwargs)
    def list_fields(self,namespace,**kwargs):
        original=self.field_pages[kwargs.get('page')]
        existing=[obj for (kind,_),obj in self.objects.items() if kind=='field']
        return NS(data=NS(items=list(original.data.items)+existing),headers=original.headers)
    def list_parsers(self,namespace,**kwargs):
        return response(NS(items=[obj for (kind,_),obj in self.objects.items() if kind=='parser']))
    def call_api(self,path,method,**kwargs):
        assert path=='/namespaces/{namespaceName}/parsers/actions/test'
        assert method=='POST' and kwargs['response_type']=='str'
        # Exercise the same nested-model type validation as the real SDK before
        # any HTTP call; util.to_dict alone does not enforce these types.
        serializer=object.__new__(oci.base_client.BaseClient)
        serializer.complex_type_mappings=vars(oci.log_analytics.models)
        serializer.sanitize_for_serialization(kwargs['body'])
        if self.raw_test_result is not None:
            return response(__import__('json').dumps(self.raw_test_result))
        result=self.test_parser(kwargs['path_params']['namespaceName'],kwargs['body'])
        values=result.data.entries[0].fields.values()
        return response(__import__('json').dumps([{str(i+1):value for i,value in enumerate(values)}]))

    def test_parser(self,namespace,payload):
        event=__import__('json').loads(payload.example_content)
        fields={}
        if not self.fail_test:
            for mapping in payload.field_maps:
                value=event
                for key in mapping.structured_column_info[2:].split('.'):
                    value=value.get(key) if isinstance(value,dict) else None
                if value is not None: fields[mapping.parser_field_name]=value
        return response(NS(entries=[NS(fields=fields)]))


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.client=FakeAnalytics()
        self.definition=schema('test')
        self.definition['example']=example_event()
    def install(self):
        installer.install(self.client,'namespace','ocid1.tenancy.oc1..TEST',self.definition,oci.log_analytics.models)

    def test_real_sdk_models_map_native_scalar_paths_and_event_time_and_source(self):
        self.install()
        writes=self.client.writes
        self.assertEqual([kind for kind,_,_ in writes],['field']*len(PATHS)+['parser','source'])
        parser=writes[-2][1]
        self.assertEqual(parser.type,'JSON')
        self.assertIsNone(parser.content)
        self.assertEqual(parser.header_content,'$:0')
        self.assertTrue(all(m.parser_field_expression is None for m in parser.field_maps))
        self.assertEqual(parser.field_maps[0].parser_field_name,'time')
        self.assertEqual(parser.field_maps[0].structured_column_info,'$.eventTime')
        self.assertEqual({m.structured_column_info for m in parser.field_maps[1:]},set(PATHS.values()))
        self.assertEqual(parser.name,self.definition['parser'])
        self.assertEqual(writes[-1][1].parsers[0].name,self.definition['parser'])
        serializer=object.__new__(oci.base_client.BaseClient)
        serializer.complex_type_mappings=vars(oci.log_analytics.models)
        self.assertEqual(serializer.sanitize_for_serialization(parser)['name'],self.definition['parser'])
        # OCI's serializer accepts every nested model; no invented model fields.
        self.assertIn('field_maps',oci.util.to_dict(parser))
        self.assertFalse(any('backup' in kind for kind,_,_ in writes))

    def test_repeat_deployment_upserts_only_owned_content_with_etags(self):
        self.install()
        self.client.writes=[]
        self.install()
        self.assertTrue(all(kwargs.get('if_match')=='etag' for _,_,kwargs in self.client.writes))

    def test_existing_canonical_source_is_updated_with_identity_and_etag(self):
        name=self.definition['display']
        self.client.objects['source',name]=NS(name=name,display_name=name,
            description=self.definition['description'],is_system=False,source_id=-6037844993762889542,
            edit_version=1794358993423)
        self.install()
        kind,source,kwargs=self.client.writes[-1]
        self.assertEqual(kind,'source')
        self.assertEqual(source.name,name)
        self.assertEqual(source.source_id,-6037844993762889542)
        self.assertEqual(source.edit_version,1794358993423)
        self.assertEqual(kwargs,{'if_match':'etag'})
        self.assertEqual(len([k for k in self.client.objects if k[0]=='source']),1)

    def test_linked_parser_update_requires_fresh_source_etag_and_edit_version(self):
        self.install()
        name=self.definition['source']
        self.client.objects['source',name].edit_version=10
        revision=['before-parser']
        order=[]
        original_get=self.client.get_source
        original_parser=self.client.upsert_parser
        original_source=self.client.upsert_source
        def get_source(ns,source_name,tenancy):
            result=original_get(ns,source_name,tenancy)
            if source_name==name:
                order.append('read-source')
                return NS(data=deepcopy(result.data),headers={'etag':revision[0]})
            return result
        def save_parser(*args,**kwargs):
            result=original_parser(*args,**kwargs)
            self.client.objects['source',name].edit_version=11
            revision[0]='after-parser'
            order.append('save-parser')
            return result
        def save_source(ns,payload,**kwargs):
            order.append('save-source')
            if kwargs.get('if_match')!=revision[0] or payload.edit_version!=11:
                raise APIError(412)
            return original_source(ns,payload,**kwargs)
        self.client.get_source=get_source
        self.client.upsert_parser=save_parser
        self.client.upsert_source=save_source
        self.client.writes=[]
        self.install()
        self.assertEqual(order,['read-source','save-parser','read-source','save-source'])
        source=self.client.writes[-1]
        self.assertEqual(source[2],{'if_match':'after-parser'})
        self.assertEqual(source[1].edit_version,11)
        self.assertEqual(source[1].source_id,123)

    def test_source_refresh_failures_never_publish_source(self):
        for failure in ('missing','foreign','replaced','missing-etag','permission'):
            with self.subTest(failure=failure):
                self.client=FakeAnalytics()
                self.install()
                original=self.client.get_source
                reads=[]
                def get_source(ns,name,tenancy):
                    result=original(ns,name,tenancy)
                    if name==self.definition['source']:
                        reads.append(name)
                        if len(reads)==2:
                            if failure=='missing':raise APIError(404)
                            if failure=='permission':raise APIError(403)
                            result=deepcopy(result)
                            if failure=='foreign':result.data.description='other owner'
                            if failure=='replaced':result.data.source_id=456
                            if failure=='missing-etag':result.headers={}
                    return result
                self.client.get_source=get_source
                self.client.upsert_source=Mock()
                observer=Mock()
                with self.assertRaises((installer.NativeSchemaError,APIError)):
                    installer.install(self.client,'namespace','tenancy',self.definition,oci.log_analytics.models,
                                      before_source_upsert=observer)
                self.client.upsert_source.assert_not_called()
                observer.assert_not_called()

    def test_concurrent_change_after_source_refresh_is_not_blindly_retried(self):
        self.install()
        error=APIError(412)
        self.client.upsert_source=Mock(side_effect=error)
        with self.assertRaises(APIError) as caught:self.install()
        self.assertIs(caught.exception,error)
        self.client.upsert_source.assert_called_once()

    def test_obsolete_generated_source_name_is_rejected_before_writes(self):
        self.definition['source']='bh_events_obsolete'
        with self.assertRaisesRegex(ValueError,'regenerate'):self.install()
        self.assertEqual(self.client.writes,[])

    def test_foreign_canonical_source_blocks_all_schema_writes(self):
        name=self.definition['display']
        self.client.objects['source',name]=NS(name=name,description='someone else',is_system=False)
        with self.assertRaisesRegex(ValueError,'not owned'):self.install()
        self.assertEqual(self.client.writes,[])

    def test_unexpected_source_identity_stops_setup(self):
        self.client.upsert_source=lambda *a,**kw:response(NS(name='unexpected'))
        with self.assertRaisesRegex(ValueError,'planned connector source name'):self.install()

    def test_source_request_observer_runs_before_source_save(self):
        captured=[]
        self.client.upsert_source=Mock(side_effect=APIError(400))
        with self.assertRaises(APIError):
            installer.install(self.client,'namespace','tenancy',self.definition,oci.log_analytics.models,
                              before_source_upsert=captured.append)
        self.assertEqual(len(captured),1)
        self.assertIs(captured[0],self.client.upsert_source.call_args.args[1])
        self.assertEqual(captured[0].name,self.definition['display'])

    def test_request_serializes_explicit_settings_observed_in_persisted_json_parsers(self):
        import json
        self.install()
        parser=self.client.writes[-2][1]
        serializer=object.__new__(oci.base_client.BaseClient)
        serializer.complex_type_mappings=vars(oci.log_analytics.models)
        body=serializer.sanitize_for_serialization(parser)
        observed=json.loads((Path(__file__).parent/'fixtures/persisted-json-parser-settings.json').read_text())['settings']
        self.assertEqual({k:body.get(k) for k in observed},observed)
        # Server-assigned reference-parser IDs must never leak into a new parser.
        self.assertNotIn('editVersion',body)
        self.assertTrue(all('parserFieldId' not in m for m in body['fieldMaps']))

    def test_request_observer_sees_identical_model_after_test_before_save(self):
        order=[]
        original=self.client.upsert_parser
        self.client.upsert_parser=lambda ns,p,**kw: (order.append(('save',p)),original(ns,p,**kw))[1]
        def observe(parser):
            self.assertTrue(all(kind=='field' for kind,_,_ in self.client.writes))
            order.append(('capture',parser))
        installer.install(self.client,'namespace','tenancy',self.definition,oci.log_analytics.models,
                          before_parser_upsert=observe)
        self.assertEqual([kind for kind,_ in order],['capture','save'])
        self.assertIs(order[0][1],order[1][1])
        self.client.fail_test=True
        observer=Mock()
        with self.assertRaisesRegex(ValueError,'parser test'):
            installer.install(self.client,'namespace','tenancy',self.definition,oci.log_analytics.models,
                              before_parser_upsert=observer)
        observer.assert_not_called()

    def test_failed_request_capture_stops_before_parser_and_source_writes(self):
        with self.assertRaisesRegex(OSError,'capture failed'):
            installer.install(self.client,'namespace','tenancy',self.definition,oci.log_analytics.models,
                              before_parser_upsert=Mock(side_effect=OSError('capture failed')))
        self.assertTrue(all(kind=='field' for kind,_,_ in self.client.writes))

    def test_permission_failure_is_not_interpreted_as_missing_or_healthy(self):
        self.client.denied=True
        with self.assertRaises(APIError): self.install()
        self.assertEqual(self.client.writes,[])

    def test_ownership_collision_stops_before_any_writes(self):
        name=self.definition['fields'][-1]['name']
        self.client.objects['field',name]=oci.log_analytics.models.LogAnalyticsField(name=name,display_name='foreign field',description='other app',is_system=False)
        with self.assertRaisesRegex(ValueError,'not owned'): self.install()
        self.assertEqual(self.client.writes,[])

    def test_missing_update_etag_fails_closed(self):
        self.install()
        self.client.writes=[]
        original=self.client.read
        self.client.read=lambda *args:NS(data=original(*args).data,headers={})
        with self.assertRaisesRegex(ValueError,'ETag'): self.install()
        self.assertEqual(self.client.writes,[])

    def test_failed_live_parser_test_does_not_publish_source_or_create_connector(self):
        self.client.fail_test=True
        with self.assertRaisesRegex(ValueError,'parser test'): self.install()
        self.assertTrue(all(kind=='field' for kind,_,_ in self.client.writes))

    def test_time_field_metadata_pagination_and_repeated_token(self):
        self.client.field_pages={None:response(NS(items=[]),**{'opc-next-page':'p2'}),
            'p2':response(NS(items=[oci.log_analytics.models.LogAnalyticsFieldSummary(name='time',display_name='Time',data_type='TIMESTAMP',is_system=True)]))}
        self.install()
        self.client.field_pages['p2']=response(NS(items=[]),**{'opc-next-page':'p2'})
        with self.assertRaisesRegex(ValueError,'Repeated'): self.install()

    def test_builtin_unified_parser_can_be_regex_with_no_content(self):
        self.install()
        self.assertNotIn('oci_unifiedschema_logtype',self.client.parser_reads)
        parser=self.client.writes[-2][1]
        self.assertEqual(parser.type,'JSON')
        self.assertIsNone(parser.content)

    def test_standard_time_metadata_missing_stops_before_writes(self):
        self.client.field_pages={None:response(NS(items=[]))}
        with self.assertRaisesRegex(ValueError,'Time field'):self.install()
        self.assertEqual(self.client.writes,[])

    def test_canonical_server_field_names_are_reused_on_retry(self):
        self.client.canonical_fields=True
        self.install()
        parser=self.client.writes[-2][1]
        self.assertTrue(all(m.parser_field_name.startswith('udfs') for m in parser.field_maps[1:]))
        before=len([key for key in self.client.objects if key[0]=='field'])
        self.client.writes=[]
        self.install()
        self.assertEqual(len([key for key in self.client.objects if key[0]=='field']),before)
        self.assertTrue(all(kwargs.get('if_match')=='etag' for _,_,kwargs in self.client.writes))

    def test_parser_gate_supports_actual_positional_array_and_documented_shape(self):
        identity=self.definition['example']['eventID']
        for result in [[{'1':identity,'2':'operationSucceed'}],
                       {'entries':[{'fieldNameValueMap':{'id':identity,'status':'operationSucceed'}}]}]:
            with self.subTest(result=result):
                self.client.raw_test_result=result
                self.install()
        self.client.raw_test_result={'unexpected':{'id':identity,'status':'operationSucceed'}}
        with self.assertRaisesRegex(ValueError,'parser test'):self.install()

    def test_field_summary_is_converted_and_passes_real_sdk_nested_serialization(self):
        from datetime import datetime, timezone
        summary=oci.log_analytics.models.LogAnalyticsFieldSummary(
            name='time',display_name='Time',data_type='TIMESTAMP',is_system=True,
            time_updated=datetime(2026,10,16,15,38,16,tzinfo=timezone.utc),
            edit_version=2132000006000000000)
        self.client.field_pages={None:response(NS(items=[summary]))}
        serializer=object.__new__(oci.base_client.BaseClient)
        serializer.complex_type_mappings=vars(oci.log_analytics.models)
        broken=oci.log_analytics.models.TestParserPayloadDetails(field_maps=[
            oci.log_analytics.models.LogAnalyticsParserField(field=summary)])
        with self.assertRaisesRegex(TypeError,'LogAnalyticsFieldSummary'):
            serializer.sanitize_for_serialization(broken)
        self.install()
        field=self.client.writes[-2][1].field_maps[0].field
        self.assertIsInstance(field,oci.log_analytics.models.LogAnalyticsField)
        self.assertNotIsInstance(field,oci.log_analytics.models.LogAnalyticsFieldSummary)
        self.assertEqual(field.time_updated,summary.time_updated)
        self.assertIsInstance(field.time_updated,datetime)
        self.assertEqual(field.edit_version,summary.edit_version)

    def test_full_field_models_are_preserved(self):
        field=oci.log_analytics.models.LogAnalyticsField(name='udfs1',data_type='STRING')
        self.assertIs(installer.parser_field_model(field,oci.log_analytics.models),field)

    def test_parser_name_is_resolved_and_reused_with_etag_on_next_run(self):
        self.install()
        self.client.writes=[]
        self.install()
        parser=self.client.writes[-2]
        self.assertEqual(parser[1].name,self.definition['parser'])
        self.assertEqual(parser[2]['if_match'],'etag')
        self.assertEqual(len([k for k in self.client.objects if k[0]=='parser']),1)

    def test_parser_display_collision_stops_before_field_writes(self):
        self.client.objects['parser','server-name']=NS(name='server-name',
            display_name=self.definition['display']+' JSON',description='another owner',is_system=False)
        with self.assertRaisesRegex(ValueError,'not owned'): self.install()
        self.assertEqual(self.client.writes,[])

    def test_ambiguous_owned_parsers_stop_before_writes(self):
        for name in ('first','second'):
            self.client.objects['parser',name]=NS(name=name,
                display_name=self.definition['display']+' JSON',
                description=self.definition['description'],is_system=False)
        with self.assertRaisesRegex(ValueError,'Ambiguous'): self.install()
        self.assertEqual(self.client.writes,[])

    def test_legacy_named_parser_is_retained(self):
        self.client.objects['parser',self.definition['parser']]=NS(name=self.definition['parser'],
            display_name=self.definition['display']+' JSON',description=self.definition['description'],is_system=False,edit_version=2)
        self.install()
        self.assertEqual(self.client.writes[-2][1].name,self.definition['parser'])

    def test_parser_discovery_pagination_and_repeated_tokens(self):
        record=NS(name='canonical',display_name=self.definition['display']+' JSON',
                  description=self.definition['description'],is_system=False,edit_version=2)
        self.client.objects['parser',record.name]=record
        self.client.list_parsers=lambda ns,**kw: (response(NS(items=[record])) if kw.get('page')
            else response(NS(items=[]),**{'opc-next-page':'next'}))
        self.install()
        self.assertEqual(self.client.writes[-2][1].name,'canonical')
        self.client.writes=[]
        self.client.list_parsers=lambda *a,**k:response(NS(items=[]),**{'opc-next-page':'again'})
        with self.assertRaisesRegex(ValueError,'Repeated'): self.install()
        self.assertEqual(self.client.writes,[])

    def test_parser_missing_canonical_response_blocks_source(self):
        self.client.upsert_parser=lambda *a,**k:response(NS(name=None))
        with self.assertRaisesRegex(ValueError,'canonical parser name'): self.install()
        self.assertFalse(any(kind=='source' for kind,_,_ in self.client.writes))

    @patch.object(installer.time,'sleep')
    def test_parser_server_error_replays_identical_payload_token_and_etag(self,sleep):
        error=oci.exceptions.ServiceError(500,'InternalError',{'opc-request-id':'request-1'},'Internal error')
        client=NS(upsert_parser=Mock(side_effect=[error,error,'success']))
        parser=object()
        with patch('sys.stderr'):
            result=installer.upsert_parser(client,'namespace',parser,response(NS()))
        self.assertEqual(result,'success')
        calls=client.upsert_parser.call_args_list
        self.assertEqual(len(calls),3)
        self.assertTrue(all(call==calls[0] for call in calls))
        self.assertIs(calls[0].args[1],parser)
        self.assertEqual(calls[0].kwargs['if_match'],'etag')
        self.assertTrue(calls[0].kwargs['opc_retry_token'])
        self.assertIsInstance(calls[0].kwargs['retry_strategy'],oci.retry.NoneRetryStrategy)
        delays=[call.args[0] for call in sleep.call_args_list]
        self.assertTrue(2<=delays[0]<=3 and 4<=delays[1]<=5)

    @patch.object(installer.time,'sleep')
    def test_persistent_parser_500_preserves_service_error_and_stops_source(self,sleep):
        error=oci.exceptions.ServiceError(500,'InternalError',{'opc-request-id':'support-id'},'Internal error')
        self.client.upsert_parser=Mock(side_effect=error)
        with patch('sys.stderr'),self.assertRaises(oci.exceptions.ServiceError) as caught:
            self.install()
        self.assertIs(caught.exception,error)
        self.assertEqual(caught.exception.headers['opc-request-id'],'support-id')
        self.assertEqual(self.client.upsert_parser.call_count,3)
        self.assertEqual(sleep.call_count,2)
        self.assertFalse(any(kind=='source' for kind,_,_ in self.client.writes))

    @patch.object(installer.time,'sleep')
    def test_parser_nonretryable_errors_are_not_replayed(self,sleep):
        for status in (400,401,403,404,409,412,501):
            with self.subTest(status=status):
                error=APIError(status)
                client=NS(upsert_parser=Mock(side_effect=error))
                with self.assertRaises(APIError):
                    installer.upsert_parser(client,'namespace',object(),None)
                self.assertEqual(client.upsert_parser.call_count,1)
        sleep.assert_not_called()

    @patch.object(installer.time,'sleep')
    def test_parser_throttling_and_unavailability_use_retry_token(self,sleep):
        for status in (429,503):
            with self.subTest(status=status):
                client=NS(upsert_parser=Mock(side_effect=[APIError(status),'success']))
                with patch('sys.stderr'):
                    self.assertEqual(installer.upsert_parser(client,'namespace',object(),None),'success')
                calls=client.upsert_parser.call_args_list
                self.assertEqual(calls[0],calls[1])
