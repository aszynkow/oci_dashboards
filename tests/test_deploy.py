import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from oci_dashboards.deploy import (ROOT, load_tfvars_settings, prepare, preflight, profile_metadata,
                                   main, plan_stack, reject_deletions, setup_schema, record_parser_request)
from oci_dashboards.tfvars import load


@unittest.skipUnless(shutil.which('terraform'),'Terraform required for real HCL parsing')
class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.profile=patch('oci.config.from_file',return_value={
            'region':'ap-sydney-1','tenancy':'ocid1.tenancy.oc1..PROFILE',
            'key_file':'NEVER_COPY_CREDENTIAL','user':'PRIVATE'})
        self.profile.start()
        self.addCleanup(self.profile.stop)
        self.example=ROOT/'terraform/terraform.tfvars.example'

    def settings(self): return load_tfvars_settings(self.example,profile='PRODUCTION')

    def test_minimal_tfvars_profile_and_offline_preparation_have_no_collector_dependency(self):
        config=self.settings()
        self.assertEqual(config['region'],'ap-sydney-1')
        self.assertEqual(config['iam_policy_compartment_id'],'ocid1.tenancy.oc1..PROFILE')
        self.assertIsNone(config['home_region'])
        self.assertIsNone(config['log_analytics_namespace'])
        with tempfile.TemporaryDirectory() as folder, patch('oci_dashboards.deploy.run',side_effect=AssertionError('cloud call')):
            output=Path(folder)
            summary=prepare(config,output)
            self.assertEqual(summary['widgets'],15)
            stack=json.loads((output/'terraform/main.tf.json').read_text())
            central=stack['module']['central']
            self.assertEqual(central['oci_profile'],'PRODUCTION')
            definition=json.loads((output/'native-event-schema.json').read_text())
            self.assertEqual(central['native_source_name'],definition['source'])
            self.assertEqual(central['native_source_name'],definition['display'])
            for path in output.rglob('*.json'):
                text=path.read_text()
                json.loads(text)
                self.assertNotIn('NEVER_COPY_CREDENTIAL',text)
                self.assertNotIn('collector_function',text)
            self.assertFalse(list(output.glob('*.tar.gz')))
            self.assertFalse((output/'collector.config.json').exists())

    def test_identity_guard_rejects_another_tenancy_or_legacy_state_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            config=self.settings()
            prepare(config,output)
            other={**config,'iam_policy_compartment_id':'ocid1.tenancy.oc1..OTHER'}
            with self.assertRaisesRegex(ValueError,'another deployment'): prepare(other,output)
            (output/'deployment-identity.json').write_text('{"mode":"legacy"}')
            with self.assertRaisesRegex(ValueError,'legacy collector state'): prepare(config,output)
            self.assertEqual(json.loads((output/'deployment-identity.json').read_text()),{'mode':'legacy'})

    def test_real_hcl_types_defaults_complex_environment_and_explicit_precedence(self):
        config=load(self.example)
        self.assertEqual(config['stream_retention_hours'],168)
        with patch.dict(os.environ,{'TF_VAR_scope_id':'from_environment','TF_CLI_ARGS_console':'-var=scope_id=wrong'}):
            self.assertEqual(load(self.example)['scope_id'],'from_environment')
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'input.tfvars'
                path.write_text(self.example.read_text()+'\nscope_id="from_file"\n')
                self.assertEqual(load(path)['scope_id'],'from_file')

    def test_json_tfvars_and_empty_or_existing_topic_options(self):
        values=load(self.example)
        for topics in ([],['ocid1.onstopic.oc1.ap-sydney-1.EXISTING']):
            values['alarm_destination_topic_ids']=topics
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'input.tfvars.json'
                path.write_text(json.dumps(values))
                config=load_tfvars_settings(path,profile='PRODUCTION')
                prepare(config,Path(folder)/'out')
                stack=json.loads((Path(folder)/'out/terraform/main.tf.json').read_text())
                self.assertEqual(stack['module']['central']['alarm_destination_topic_ids'],topics)

    def test_existing_stream_option_is_passed_through_without_allocating_stream_partitions_in_python(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reuse.tfvars'
            path.write_text(self.example.read_text()+'\nexisting_stream_id="ocid1.stream.oc1.ap-sydney-1.EXISTING"\n')
            config=load_tfvars_settings(path,profile='PRODUCTION')
            prepare(config,Path(folder)/'out')
            stack=json.loads((Path(folder)/'out/terraform/main.tf.json').read_text())
            self.assertEqual(stack['module']['central']['existing_stream_id'],'ocid1.stream.oc1.ap-sydney-1.EXISTING')

    def test_existing_stream_rejects_non_stream_identifiers(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reuse.tfvars'
            path.write_text(self.example.read_text()+'\nexisting_stream_id="ocid1.streampool.oc1.ap-sydney-1.NOT_A_STREAM"\n')
            with self.assertRaises(ValueError):load_tfvars_settings(path,profile='PRODUCTION')

    def test_deprecated_collector_or_generated_file_inputs_fail_closed(self):
        for setting in ('enable_collector=false','collector_function_image="old"','native_schema_file="other.json"',
                        'stream_retention_hours=1','inventory_compartment_ids=[]'):
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'input.tfvars'
                # Avoid duplicate declaration error for the source-list case.
                text=self.example.read_text()
                if setting.startswith('inventory_'):
                    text='\n'.join(l for l in text.splitlines() if not l.startswith('inventory_compartment_ids'))
                path.write_text(text+'\n'+setting)
                with self.assertRaises(ValueError):load_tfvars_settings(path,profile='PRODUCTION')

    def test_invalid_input_diagnostics_do_not_echo_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.tfvars'
            path.write_text(self.example.read_text()+'\nunknown_secret="DO_NOT_ECHO"')
            with self.assertRaises(ValueError) as raised:load(path)
            self.assertNotIn('DO_NOT_ECHO',str(raised.exception))

    def test_profile_identifiers_are_authoritative_and_private_fields_not_returned(self):
        self.assertEqual(profile_metadata('PRODUCTION'),{'region':'ap-sydney-1','tenancy':'ocid1.tenancy.oc1..PROFILE'})
        with patch.dict(os.environ,{'TF_VAR_region':'wrong','TF_VAR_home_region':'wrong',
             'TF_VAR_iam_policy_compartment_id':'ocid1.tenancy.oc1..OTHER'}):
            config=self.settings()
            self.assertEqual(config['region'],'ap-sydney-1')
            self.assertEqual(config['iam_policy_compartment_id'],'ocid1.tenancy.oc1..PROFILE')
            self.assertIsNone(config['home_region'])

    def test_missing_profile_or_identifiers_fail_with_redacted_errors(self):
        with patch('oci.config.from_file',side_effect=RuntimeError('SECRET')):
            with self.assertRaises(ValueError) as raised:profile_metadata('MISSING')
            self.assertNotIn('SECRET',str(raised.exception))
        with patch('oci.config.from_file',return_value={'region':'ap-sydney-1'}):
            with self.assertRaisesRegex(ValueError,'tenancy OCID'):profile_metadata('INCOMPLETE')

    def test_preflight_rejects_placeholders_before_any_cloud_actions(self):
        with self.assertRaisesRegex(ValueError,'placeholder'):preflight(self.settings())

    def test_prepare_is_default_and_apply_uses_only_reviewed_tf_plan(self):
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            argv=['--tfvars',str(self.example),'--profile','PRODUCTION','--output',folder]
            with patch('oci_dashboards.deploy.plan_stack',side_effect=AssertionError('plan called')), patch('oci_dashboards.deploy.setup_schema',side_effect=AssertionError('schema called')):
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(argv),0)
            outputs={k:{'value':v} for k,v in {'stream_id':'stream','connector_id':'connector',
                'home_region':'us-ashburn-1','log_analytics_namespace':'namespace'}.items()}
            calls=[]
            order=[]
            def fake_run(command,**kwargs):
                calls.append(command)
                if 'apply' in command:order.append('apply')
                return NS(stdout=json.dumps(outputs) if 'output' in command else '')
            with patch('oci_dashboards.deploy.preflight'), patch('oci_dashboards.deploy.plan_stack',return_value=['terraform','-chdir=fake']), patch('oci_dashboards.deploy.run',side_effect=fake_run), patch('oci_dashboards.deploy.setup_schema',side_effect=lambda *_:order.append('schema')):
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(argv+['--apply']),0)
            self.assertEqual(order,['schema','apply'])
            self.assertEqual(calls[0][-3:],['apply','-input=false','deployment.tfplan'])
            receipt=json.loads((Path(folder)/'receipt.json').read_text())
            self.assertEqual(receipt['home_region'],'us-ashburn-1')
            self.assertFalse(any('ssh' in str(call) or 'docker' in str(call) for call in calls))

    def test_plan_never_calls_python_schema_setup(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            with patch('oci_dashboards.deploy.preflight'), patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']), \
                 patch('oci_dashboards.deploy.setup_schema') as install_schema, patch('oci_dashboards.deploy.run') as execute:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--tfvars',str(self.example),'--profile','PRODUCTION','--output',folder,'--plan']),0)
                install_schema.assert_not_called()
                execute.assert_not_called()

    def test_python_schema_error_stops_tf_apply_and_keeps_original_type_message(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            with patch('oci_dashboards.deploy.preflight'), patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']), \
                 patch('oci_dashboards.deploy.setup_schema',side_effect=TypeError('synthetic bad field type')), \
                 patch('oci_dashboards.deploy.run') as execute:
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(TypeError,'synthetic bad field type'):
                    main(['--tfvars',str(self.example),'--profile','PRODUCTION','--output',folder,'--apply'])
                execute.assert_not_called()
                self.assertFalse((Path(folder)/'receipt.json').exists())

    def test_schema_namespace_comes_from_reviewed_plan_and_direct_sdk_call(self):
        config=self.settings()
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            prepare(config,output)
            (output/'terraform-plan.json').write_text(json.dumps({'planned_values':{'outputs':{
                'log_analytics_namespace':{'value':'resolved_namespace'}}}}))
            client=object()
            with patch('oci.log_analytics.LogAnalyticsClient',return_value=client), patch('oci_dashboards.native_schema.install') as install_schema:
                setup_schema(config,output)
                args=install_schema.call_args.args
                self.assertIs(args[0],client)
                self.assertEqual(args[1],'resolved_namespace')
                self.assertEqual(args[2],config['iam_policy_compartment_id'])
                self.assertEqual(args[3]['scope_id'],config['scope_id'])

    def test_unresolved_plan_namespace_never_constructs_sdk_client(self):
        config=self.settings()
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            prepare(config,output)
            (output/'terraform-plan.json').write_text('{}')
            with patch('oci.log_analytics.LogAnalyticsClient') as client, self.assertRaisesRegex(ValueError,'did not resolve'):
                setup_schema(config,output)
            client.assert_not_called()

    def test_parser_body_capture_uses_real_sdk_serialization_private_files_and_hash(self):
        import hashlib
        import oci
        serializer=object.__new__(oci.base_client.BaseClient)
        serializer.complex_type_mappings=vars(oci.log_analytics.models)
        # Extra client properties must not be captured: body only, no config or headers.
        client=NS(base_client=serializer,config={'key_content':'NEVER_CAPTURE'},headers={'authorization':'NEVER_CAPTURE'})
        parser=oci.log_analytics.models.UpsertLogAnalyticsParserDetails(
            name='parser',type='JSON',example_content='{"eventID":"SYNTHETIC"}',is_default=True)
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            output=Path(folder)
            record_parser_request(client,parser,output)
            path=output/'parser-upsert.request.json'
            metadata=json.loads((output/'parser-upsert.request.metadata.json').read_text())
            self.assertEqual(json.loads(path.read_text()),serializer.sanitize_for_serialization(parser))
            self.assertEqual(metadata['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(metadata['operation'],'upsert_parser')
            self.assertNotIn('NEVER_CAPTURE',path.read_text())
            for item in output.iterdir():self.assertEqual(item.stat().st_mode & 0o777,0o600)

    def test_changed_profile_or_schema_scope_never_starts_schema_writes(self):
        config=self.settings()
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            prepare(config,output)
            (output/'terraform-plan.json').write_text(json.dumps({'planned_values':{'outputs':{
                'log_analytics_namespace':{'value':'resolved_namespace'}}}}))
            with patch('oci.config.from_file',return_value={'region':'other','tenancy':'other'}), \
                 patch('oci.log_analytics.LogAnalyticsClient') as client, self.assertRaisesRegex(ValueError,'changed after planning'):
                setup_schema(config,output)
            client.assert_not_called()
            definition=json.loads((output/'native-event-schema.json').read_text())
            definition['scope_id']='other'
            (output/'native-event-schema.json').write_text(json.dumps(definition))
            with patch('oci.log_analytics.LogAnalyticsClient') as client, self.assertRaisesRegex(ValueError,'does not match'):
                setup_schema(config,output)
            client.assert_not_called()

    def test_get_update_supports_linked_or_copied_modules_without_provider_upgrade(self):
        # Reproduce the actual file:// cache boundary, not a fake file-copy model.
        environment={k:v for k,v in os.environ.items() if not k.startswith(('TF_VAR_','TF_CLI_ARGS','TF_LOG'))}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'root'
            source=Path(folder)/'source'
            root.mkdir()
            source.mkdir()
            file=source/'main.tf'
            file.write_text('output "marker" { value = "before" }\n')
            (root/'main.tf.json').write_text(json.dumps({'module':{'example':{'source':source.as_uri()}}}))
            prefix=[shutil.which('terraform'),'-chdir='+str(root)]
            subprocess.run(prefix+['get'],check=True,capture_output=True,text=True,env=environment,timeout=30)
            manifest=json.loads((root/'.terraform/modules/modules.json').read_text())
            cached=next(item['Dir'] for item in manifest['Modules'] if item['Key']=='example')
            cached=Path(cached) if Path(cached).is_absolute() else root/cached
            self.assertIn('before',(cached/'main.tf').read_text())
            replacement=source/'replacement.tmp'
            replacement.write_text('output "marker" { value = "after" }\n')
            replacement.replace(file) # Atomic editor saves break a cached hard link.
            if not cached.is_symlink():
                self.assertIn('before',(cached/'main.tf').read_text())
            subprocess.run(prefix+['get','-update'],check=True,capture_output=True,text=True,env=environment,timeout=30)
            self.assertIn('after',(cached/'main.tf').read_text())
            self.assertFalse((root/'.terraform.lock.hcl').exists()) # No provider operation performed.

    def test_plan_rejects_deletion_before_apply_and_does_not_run_schema_upserts(self):
        calls=[]
        def fake_run(argv,**kwargs):
            calls.append(argv)
            return NS(stdout=json.dumps({'resource_changes':[{'address':'stream','type':'oci_streaming_stream',
                'change':{'actions':['delete','create']}}]}) if 'show' in argv else '')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'refuses'):plan_stack(Path(folder),execute=fake_run)
        self.assertEqual([call[2] for call in calls],['get','init','validate','plan','show'])


class PlanGuardTests(unittest.TestCase):
    def test_real_resource_deletes_and_unrelated_local_marker_replacements_are_refused(self):
        for kind,address in [('oci_streaming_stream','stream'),('terraform_data','other')]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                reject_deletions({'resource_changes':[{'address':address,'type':kind,'change':{'actions':['delete','create']}}]})

    def test_only_owned_schema_marker_and_noop_dashboard_import_allow_replace(self):
        marker={'owner':'oci-dashboards-native-schema-v1'}
        for kind,address,extra in [
            ('oci_management_dashboard_management_dashboards_import','dashboard',{}),
            ('terraform_data','module.central.terraform_data.native_schema',{'before':{'input':marker},'after':{'input':marker}})]:
            reject_deletions({'resource_changes':[{'address':address,'type':kind,
                'change':{'actions':['delete','create'],**extra}}]})
