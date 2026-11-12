"""Two-stage ordering, state safety, Docker/Colima and immutable image tests. Offline."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
from oci_dashboards import registry_deploy as R
from oci_dashboards.deploy import prepare,ROOT

D='sha256:'+'a'*64
CFG={'scope_id':'test','oci_profile':'TEST','region':'ap-sydney-1','iam_policy_compartment_id':'ocid1.tenancy.oc1..TEST',
     'telemetry_compartment_id':'ocid1.compartment.oc1..TEST','coverage_repository_name':'backup-coverage'}


class RegistryTests(unittest.TestCase):
    def registry(self,repo=None,digest=None):
        return NS(host='syd.ocir.io',namespace='namespace',repository=Mock(return_value=repo),image=Mock(return_value=digest))

    def test_offline_bootstrap_has_separate_state_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);path=R.bootstrap(CFG,out)
            stack=json.loads((path/'terraform/main.tf.json').read_text())
            self.assertEqual(stack['module']['registry']['repository_name'],'backup-coverage')
            self.assertIsNone(stack['module']['registry']['existing_repository_id'])
            self.assertFalse((out/'terraform/terraform.tfstate').exists())
            with self.assertRaisesRegex(ValueError,'another repository'):R.bootstrap({**CFG,'coverage_repository_name':'other'},out)
            # New repository state is never switched into an unmanaged lookup.
            state={'resources':[{'type':'oci_artifacts_container_repository','mode':'managed','instances':[{'attributes':{'id':'repo1'}}]}]}
            (path/'terraform/terraform.tfstate').write_text(json.dumps(state))
            R.bootstrap({**CFG,'coverage_existing_repository_id':'repo1'},out,existing_id='repo1')
            self.assertIsNone(json.loads((path/'terraform/main.tf.json').read_text())['module']['registry']['existing_repository_id'])
            with self.assertRaisesRegex(ValueError,'conflicts'):R.bootstrap({**CFG,'coverage_existing_repository_id':'different'},out)

    def test_pending_plan_has_no_docker_apply_or_push(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=self.registry()), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']),patch('oci_dashboards.deploy.run') as execute, \
             patch.object(R,'docker_ready') as docker,patch.object(R,'build_push') as build:
            self.assertIsNone(R.resolve(CFG,Path(folder)))
            execute.assert_not_called();docker.assert_not_called();build.assert_not_called()
            self.assertTrue((Path(folder)/'ocir/terraform/main.tf.json').exists())

    def test_apply_order_and_pinned_digest(self):
        order=[];registry=self.registry();registry.image.return_value=D
        def execute(command,**kwargs):
            if 'apply' in command:order.append('repository apply')
            return NS(stdout=json.dumps({'repository_id':{'value':'repo1'},'namespace':{'value':'namespace'}}))
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack',side_effect=lambda *_:order.append('repository plan') or ['terraform']), \
             patch('oci_dashboards.deploy.run',side_effect=execute), \
             patch.object(R,'docker_ready',side_effect=lambda *a,**kw:order.append('docker check') or ['docker']), \
             patch.object(R,'build_push',side_effect=lambda *a,**kw:order.append('build push') or D):
            uri=R.resolve(CFG,Path(folder),apply=True)
            self.assertEqual(order,['repository plan','docker check','repository apply','build push'])
            self.assertEqual(uri,'syd.ocir.io/namespace/backup-coverage:src-'+R.source_hash()[:24]+'@'+D)
            receipt=json.loads((Path(folder)/'coverage-image.json').read_text())
            self.assertEqual(receipt['digest'],D)

    def test_build_failure_stops_before_digest_receipt(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=self.registry()), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']), \
             patch('oci_dashboards.deploy.run',return_value=NS(stdout=json.dumps({'repository_id':{'value':'repo1'},'namespace':{'value':'namespace'}}))), \
             patch.object(R,'docker_ready',return_value=['docker']),patch.object(R,'build_push',side_effect=RuntimeError('build failed')):
            with self.assertRaisesRegex(RuntimeError,'build failed'):R.resolve(CFG,Path(folder),apply=True)
            self.assertFalse((Path(folder)/'coverage-image.json').exists())
            self.assertTrue((Path(folder)/'ocir/deployment-identity.json').exists())

    def test_tag_collision_never_overwrites_existing_image(self):
        repo=NS(id='repo1');registry=self.registry(repo,D)
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']),patch.object(R,'build_push') as build, \
             patch('oci_dashboards.deploy.run') as execute:
            with self.assertRaisesRegex(ValueError,'never overwritten'):R.resolve(CFG,Path(folder),apply=True)
            build.assert_not_called();execute.assert_not_called()

    def test_verified_receipt_reuses_image_but_checks_registry(self):
        registry=self.registry(NS(id='repo1'),D)
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']),patch.object(R,'build_push') as build, \
             patch.object(R,'docker_ready') as docker,patch('oci_dashboards.deploy.run') as execute:
            out=Path(folder);fingerprint=R.source_hash();uri='syd.ocir.io/namespace/backup-coverage:src-'+fingerprint[:24]
            (out/'coverage-image.json').write_text(json.dumps({'source_hash':fingerprint,'tag_uri':uri,'digest':D}))
            self.assertEqual(R.resolve(CFG,out),uri+'@'+D)
            registry.image.assert_called_once();execute.assert_not_called();docker.assert_not_called();build.assert_not_called()

    def test_mismatched_pushed_digest_refuses_deployment(self):
        registry=self.registry();registry.image.return_value='sha256:'+'b'*64
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']), \
             patch('oci_dashboards.deploy.run',return_value=NS(stdout=json.dumps({'repository_id':{'value':'repo1'},'namespace':{'value':'namespace'}}))), \
             patch.object(R,'docker_ready',return_value=['docker']),patch.object(R,'build_push',return_value=D):
            with self.assertRaisesRegex(ValueError,'differs'):R.resolve(CFG,Path(folder),apply=True)
            self.assertFalse((Path(folder)/'coverage-image.json').exists())

    def test_registry_resolution_rejects_public_and_ambiguous_images(self):
        reg=object.__new__(R.Registry);reg.compartment='c';reg.client=Mock()
        reg.repositories=Mock(return_value=[NS(id='repo',display_name='backup-coverage',compartment_id='c',is_public=True,lifecycle_state='AVAILABLE')])
        with self.assertRaisesRegex(ValueError,'private'):reg.repository('backup-coverage')
        rows=NS(data=[NS(repository_id='repo',lifecycle_state='AVAILABLE',version='v1',digest=D),
                      NS(repository_id='repo',lifecycle_state='AVAILABLE',version='v1',digest='sha256:'+'b'*64)])
        with patch('oci.pagination.list_call_get_all_results',return_value=rows),self.assertRaisesRegex(ValueError,'Ambiguous'):
            reg.image('repo',version='v1')


class DockerTests(unittest.TestCase):
    def test_build_push_digest_and_context_no_shell(self):
        execute=Mock(return_value=NS(stdout='tag: digest: '+D+' size: 123'))
        with patch.object(R,'source_hash',return_value='fingerprint'):
            self.assertEqual(R.build_push('syd.ocir.io/ns/repo:v1','fingerprint',prefix=R.docker_prefix('colima'),execute=execute),D)
        build,push=execute.call_args_list
        self.assertEqual(build.args[0][:3],['docker','--context','colima'])
        self.assertIn('linux/amd64',build.args[0]);self.assertIn('type=docker,oci-mediatypes=false',build.args[0]);self.assertIn('--provenance=false',build.args[0]);self.assertEqual(build.args[0][3:5],['buildx','build']);self.assertEqual(push.args[0][-2:],['push','syd.ocir.io/ns/repo:v1'])
        with self.assertRaises(ValueError):R.docker_prefix('--host=bad')

    def test_colima_is_not_started_without_explicit_flag(self):
        execute=Mock(side_effect=subprocess.CalledProcessError(1,['docker']))
        with patch('shutil.which',return_value='/bin/tool'),self.assertRaisesRegex(ValueError,'engine unavailable'):
            R.docker_ready('syd.ocir.io',execute=execute)
        self.assertEqual(execute.call_count,1)

    def test_colima_explicit_start_and_credentials_not_logged(self):
        execute=Mock(side_effect=[subprocess.CalledProcessError(1,['docker']),NS(stdout=''),NS(stdout='linux'),NS(stdout='buildx v0.test')])
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'DOCKER_CONFIG':folder}),patch('shutil.which',return_value='/bin/tool'):
            (Path(folder)/'config.json').write_text(json.dumps({'auths':{'syd.ocir.io':{'auth':'PRIVATE_NEVER_LOG'}}}))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                prefix=R.docker_ready('syd.ocir.io',start_colima=True,execute=execute)
            self.assertEqual(prefix,['docker','--context','colima'])
            self.assertEqual(execute.call_args_list[1].args[0],['colima','start','--runtime','docker'])
            self.assertNotIn('PRIVATE_NEVER_LOG',output.getvalue())

    def test_missing_docker_login_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'DOCKER_CONFIG':folder}),patch('shutil.which',return_value='/bin/tool'):
            with self.assertRaisesRegex(ValueError,'docker login syd.ocir.io'):
                R.docker_ready('syd.ocir.io',execute=Mock(return_value=NS(stdout='linux')))

class WorkflowTests(unittest.TestCase):
    def config(self):
        return {'enable_coverage':True,'coverage_function_image':None,**CFG}

    def test_pending_image_plan_previews_dashboard_without_installing_schema(self):
        from oci_dashboards.deploy import main
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder, \
             patch('oci_dashboards.deploy.load_tfvars_settings',return_value=self.config()), \
             patch('oci_dashboards.deploy.prepare',return_value={}),patch('oci_dashboards.deploy.preflight'), \
             patch.object(R,'resolve',return_value=None) as resolve,patch('oci_dashboards.deploy.plan_stack') as plan, \
             patch('oci_dashboards.deploy.preliminary_dashboard_plan') as preview, \
             patch('oci_dashboards.deploy.setup_schema') as schema,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--plan','--output',folder]),0)
            self.assertFalse(resolve.call_args.kwargs['apply']);preview.assert_called_once();plan.assert_not_called();schema.assert_not_called()

    def test_image_stage_precedes_final_plan_schema_and_apply(self):
        from oci_dashboards.deploy import main
        order=[]
        def prepare(config,output):
            if config.get('coverage_function_image'):self.assertTrue(config['coverage_function_image'].endswith('@'+D))
            return {}
        def run(command,**kwargs):
            if 'apply' in command:order.append('dashboard apply')
            return NS(stdout='{}')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder, \
             patch('oci_dashboards.deploy.load_tfvars_settings',return_value=self.config()), \
             patch('oci_dashboards.deploy.prepare',side_effect=prepare),patch('oci_dashboards.deploy.preflight'), \
             patch.object(R,'resolve',side_effect=lambda *a,**kw:order.append('repository image stage') or 'syd.ocir.io/ns/repo@'+D), \
             patch('oci_dashboards.deploy.plan_stack',side_effect=lambda *_:order.append('final dashboard plan') or ['terraform']), \
             patch('oci_dashboards.deploy.setup_schema',side_effect=lambda *_:order.append('schema')), \
             patch('oci_dashboards.deploy.run',side_effect=run),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--apply','--output',folder]),0)
        self.assertEqual(order,['repository image stage','final dashboard plan','schema','dashboard apply'])

    def test_image_error_stops_dashboard_plan_and_schema(self):
        from oci_dashboards.deploy import main
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder, \
             patch('oci_dashboards.deploy.load_tfvars_settings',return_value=self.config()), \
             patch('oci_dashboards.deploy.prepare',return_value={}),patch('oci_dashboards.deploy.preflight'), \
             patch.object(R,'resolve',side_effect=ValueError('push failed')), \
             patch('oci_dashboards.deploy.plan_stack') as plan,patch('oci_dashboards.deploy.setup_schema') as schema:
            with self.assertRaisesRegex(ValueError,'push failed'):main(['--apply','--output',folder])
            plan.assert_not_called();schema.assert_not_called()

    def test_prepare_without_image_does_not_construct_registry_or_docker(self):
        from oci_dashboards.deploy import load_tfvars_settings
        with tempfile.TemporaryDirectory() as folder,patch('oci.config.from_file',return_value={'region':'ap-sydney-1','tenancy':'ocid1.tenancy.oc1..TEST'}), \
             patch.object(R,'Registry',side_effect=AssertionError('cloud access')), \
             patch.object(R,'engine_ready',side_effect=AssertionError('docker access')):
            path=Path(folder);tfvars=path/'settings.tfvars'
            tfvars.write_text((ROOT/'terraform/terraform.tfvars.example').read_text()+'\nenable_coverage=true\ncoverage_subnet_ids=["ocid1.subnet.oc1.ap-sydney-1.TEST"]\n')
            config=load_tfvars_settings(tfvars,profile='TEST')
            prepare(config,path/'out')
            self.assertIsNone(config['coverage_function_image'])
            self.assertTrue((path/'out/ocir/terraform/main.tf.json').exists())
            self.assertTrue((path/'out/coverage.management.api.json').exists())

    def test_derive_registry_and_namespace_with_profile_consistency(self):
        config={**CFG,'coverage_registry_host':None}
        with patch('oci.config.from_file',return_value={'region':'ap-sydney-1','tenancy':CFG['iam_policy_compartment_id']}), \
             patch('oci.artifacts.ArtifactsClient'),patch('oci.object_storage.ObjectStorageClient') as storage:
            storage.return_value.get_namespace.return_value.data='example_namespace'
            registry=R.Registry(config)
            self.assertEqual(registry.host,'syd.ocir.io');self.assertEqual(registry.namespace,'example_namespace')
        with patch('oci.config.from_file',return_value={'region':'other','tenancy':'other'}),self.assertRaisesRegex(ValueError,'changed'):
            R.Registry(config)

class AdditionalImageGuards(unittest.TestCase):
    def test_existing_image_override_skips_bootstrap_and_docker(self):
        registry=NS(existing_image=Mock(return_value='syd.ocir.io/ns/repo@'+D))
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack') as plan,patch.object(R,'build_push') as build:
            self.assertEqual(R.resolve({**CFG,'coverage_function_image':'syd.ocir.io/ns/repo:v1'},Path(folder),apply=True),'syd.ocir.io/ns/repo@'+D)
            plan.assert_not_called();build.assert_not_called()
            self.assertFalse((Path(folder)/'ocir').exists())

    def test_source_change_during_build_prevents_push(self):
        execute=Mock()
        with patch.object(R,'source_hash',return_value='changed'),self.assertRaisesRegex(ValueError,'source changed'):
            R.build_push('syd.ocir.io/ns/repo:v1','original',execute=execute)
        self.assertEqual(execute.call_count,1)

    def test_existing_image_tag_resolves_to_digest_and_foreign_namespace_rejected(self):
        registry=object.__new__(R.Registry);registry.host='syd.ocir.io';registry.namespace='ns'
        registry.repository=Mock(return_value=NS(id='repo'));registry.image=Mock(return_value=D)
        self.assertEqual(registry.existing_image('syd.ocir.io/ns/repo:v1'),'syd.ocir.io/ns/repo:v1@'+D)
        registry.image.assert_called_once_with('repo',version='v1',digest=None)
        with self.assertRaisesRegex(ValueError,'namespace'):registry.existing_image('syd.ocir.io/other/repo:v1')

class RepositoryCompartmentDefaults(unittest.TestCase):
    def test_dashboard_default_override_and_dashboard_fallback(self):
        config={**CFG,'dashboard_compartment_id':'ocid1.compartment.oc1..DASHBOARD'}
        self.assertEqual(R.repository_compartment(config),config['dashboard_compartment_id'])
        self.assertEqual(R.repository_compartment({**config,'coverage_repository_compartment_id':'override'}),'override')
        self.assertEqual(R.repository_compartment({**config,'dashboard_compartment_id':None}),config['telemetry_compartment_id'])
        with tempfile.TemporaryDirectory() as folder:
            path=R.bootstrap(config,Path(folder))
            module=json.loads((path/'terraform/main.tf.json').read_text())['module']['registry']
            self.assertEqual(module['compartment_id'],config['dashboard_compartment_id'])
            with self.assertRaisesRegex(ValueError,'coverage_repository_compartment_id'):
                R.bootstrap({**config,'dashboard_compartment_id':'different'},Path(folder))
            # An explicit override retains the old repository even if dashboard placement changes.
            R.bootstrap({**config,'dashboard_compartment_id':'different','coverage_repository_compartment_id':config['dashboard_compartment_id']},Path(folder))

    def test_registry_lookup_uses_same_dashboard_default(self):
        config={**CFG,'dashboard_compartment_id':'ocid1.compartment.oc1..DASHBOARD'}
        with patch('oci.config.from_file',return_value={'region':'ap-sydney-1','tenancy':CFG['iam_policy_compartment_id']}), \
             patch('oci.artifacts.ArtifactsClient'),patch('oci.object_storage.ObjectStorageClient') as storage:
            storage.return_value.get_namespace.return_value.data='namespace'
            self.assertEqual(R.Registry(config).compartment,config['dashboard_compartment_id'])
            self.assertEqual(R.Registry({**config,'coverage_repository_compartment_id':'override'}).compartment,'override')

class RealSDKPagination(unittest.TestCase):
    """Use the real paginator and Collection models; mock only HTTP API responses."""
    def registry(self):
        reg=object.__new__(R.Registry);reg.compartment='c';reg.client=Mock()
        reg.client.list_container_repositories.__name__='list_container_repositories'
        reg.client.list_container_images.__name__='list_container_images'
        return reg

    def test_repository_collections_are_flattened_across_pages(self):
        import oci
        M=oci.artifacts.models
        reg=self.registry()
        first=M.ContainerRepositorySummary(id='repo1',display_name='backup-coverage',compartment_id='c',is_public=False,lifecycle_state='AVAILABLE')
        second=M.ContainerRepositorySummary(id='repo2',display_name='other',compartment_id='c',is_public=False,lifecycle_state='AVAILABLE')
        reg.client.list_container_repositories.side_effect=[
            oci.response.Response(200,{'opc-next-page':'page2'},M.ContainerRepositoryCollection(items=[first]),None),
            oci.response.Response(200,{},M.ContainerRepositoryCollection(items=[second]),None)]
        self.assertEqual(reg.repositories('backup-coverage'),[first,second])
        self.assertEqual(reg.client.list_container_repositories.call_args.kwargs['page'],'page2')

    def test_empty_collection_is_an_empty_list_not_items_error(self):
        import oci
        reg=self.registry()
        reg.client.list_container_repositories.return_value=oci.response.Response(
            200,{},oci.artifacts.models.ContainerRepositoryCollection(items=[]),None)
        self.assertIsNone(reg.repository('backup-coverage'))

    def test_image_collections_are_flattened_and_exactly_filtered(self):
        import oci
        M=oci.artifacts.models
        reg=self.registry()
        unrelated=M.ContainerImageSummary(repository_id='other',version='v1',digest='sha256:'+'b'*64,lifecycle_state='AVAILABLE')
        image=M.ContainerImageSummary(repository_id='repo',version='v1',digest=D,lifecycle_state='AVAILABLE')
        reg.client.list_container_images.side_effect=[
            oci.response.Response(200,{'opc-next-page':'page2'},M.ContainerImageCollection(items=[unrelated]),None),
            oci.response.Response(200,{},M.ContainerImageCollection(items=[image]),None)]
        self.assertEqual(reg.image('repo',version='v1'),D)
        self.assertEqual(reg.client.list_container_images.call_args.kwargs['page'],'page2')

class PreliminaryPreviewTests(unittest.TestCase):
    def test_wrapper_restored_after_preview_success_and_failure(self):
        from oci_dashboards.deploy import preliminary_dashboard_plan
        for failure in (False, True):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                out=Path(folder);(out/'terraform').mkdir();wrapper=out/'terraform/main.tf.json'
                original={'module':{'central':{'coverage_function_image':None}}}
                wrapper.write_text(json.dumps(original))
                def preview(output,**kwargs):
                    self.assertTrue(kwargs['preliminary'])
                    current=json.loads(wrapper.read_text())
                    self.assertEqual(current['image'],'syd.ocir.io/ns/repo:pending')
                    if failure:raise ValueError('preview rejected')
                with patch('oci_dashboards.deploy.terraform_stack',side_effect=lambda c,o:{'image':c['coverage_function_image']}), \
                     patch('oci_dashboards.deploy.plan_stack',side_effect=preview),contextlib.redirect_stdout(io.StringIO()):
                    if failure:
                        with self.assertRaisesRegex(ValueError,'preview rejected'):
                            preliminary_dashboard_plan(CFG,out,'syd.ocir.io/ns/repo:pending')
                    else:preliminary_dashboard_plan(CFG,out,'syd.ocir.io/ns/repo:pending')
                self.assertEqual(json.loads(wrapper.read_text()),original)

    def test_preview_binary_removed_and_old_final_plan_invalidated_even_on_deletion_guard(self):
        from oci_dashboards.deploy import plan_stack
        for deletion in (False,True):
            with self.subTest(deletion=deletion),tempfile.TemporaryDirectory() as folder:
                out=Path(folder);(out/'terraform').mkdir()
                (out/'terraform/deployment.tfplan').write_text('old final plan')
                (out/'terraform-plan.json').write_text('{}')
                change={'resource_changes':[{'address':'volume','type':'oci_core_volume','change':{'actions':['delete']}}]} if deletion else {'resource_changes':[]}
                binaries=[]
                def execute(command,**kwargs):
                    if 'plan' in command:
                        binary=Path(next(v[5:] for v in command if v.startswith('-out=')))
                        binary.write_text('temporary binary');binaries.append(binary)
                    return NS(stdout=json.dumps(change))
                if deletion:
                    with self.assertRaisesRegex(ValueError,'refuses'):plan_stack(out,execute=execute,preliminary=True)
                else:plan_stack(out,execute=execute,preliminary=True)
                self.assertFalse(any(p.exists() for p in binaries))
                self.assertFalse((out/'terraform/deployment.tfplan').exists())
                self.assertFalse((out/'terraform-plan.json').exists())
                result=json.loads((out/'terraform-preliminary-plan.json').read_text())
                self.assertTrue(result['preliminary']);self.assertFalse(result['apply_allowed'])

    def test_callback_failure_stops_before_repository_apply_or_docker(self):
        registry=NS(host='syd.ocir.io',namespace='namespace',repository=Mock(return_value=None),image=Mock(return_value=None))
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']),patch('oci_dashboards.deploy.run') as execute, \
             patch.object(R,'docker_ready') as docker:
            with self.assertRaisesRegex(ValueError,'unsafe dashboard'):
                R.resolve(CFG,Path(folder),apply=True,before_publication=Mock(side_effect=ValueError('unsafe dashboard')))
            execute.assert_not_called();docker.assert_not_called()

    def test_callback_runs_before_repository_apply_and_image_push(self):
        order=[];registry=NS(host='syd.ocir.io',namespace='namespace',repository=Mock(return_value=None),image=Mock(return_value=D))
        def execute(command,**kwargs):
            if 'apply' in command:order.append('repository apply')
            return NS(stdout=json.dumps({'repository_id':{'value':'repo1'},'namespace':{'value':'namespace'}}))
        with tempfile.TemporaryDirectory() as folder,patch.object(R,'Registry',return_value=registry), \
             patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']),patch('oci_dashboards.deploy.run',side_effect=execute), \
             patch.object(R,'docker_ready',return_value=['docker']),patch.object(R,'build_push',side_effect=lambda *a,**kw:order.append('image push') or D):
            R.resolve(CFG,Path(folder),apply=True,before_publication=lambda uri:order.append('dashboard preview'))
        self.assertEqual(order,['dashboard preview','repository apply','image push'])

    @unittest.skipUnless(__import__('shutil').which('terraform'),'Terraform required')
    def test_real_offline_terraform_preview_keeps_only_labelled_json(self):
        from oci_dashboards.deploy import plan_stack
        import os
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);(out/'terraform').mkdir()
            (out/'terraform/main.tf').write_text('resource "terraform_data" "preview" { input = "unpublished-image" }\n')
            def execute(command,**kwargs):
                return subprocess.run(command,check=True,capture_output=True,text=True,
                    env={k:v for k,v in os.environ.items() if not k.startswith(('TF_VAR_','TF_CLI_ARGS','TF_LOG'))})
            plan_stack(out,execute=execute,preliminary=True)
            report=json.loads((out/'terraform-preliminary-plan.json').read_text())
            self.assertEqual(report['plan']['resource_changes'][0]['change']['actions'],['create'])
            self.assertFalse(list(out.rglob('*.tfplan')))


class BuildxPreflight(unittest.TestCase):
    def test_missing_buildx_fails_before_build_or_push(self):
        execute=Mock(side_effect=[NS(stdout='linux'),subprocess.CalledProcessError(1,['docker','buildx','version'])])
        with patch('shutil.which',return_value='/bin/docker'),self.assertRaisesRegex(ValueError,'Buildx is required'):
            R.engine_ready(context='colima',execute=execute)
        self.assertEqual(execute.call_count,2)
        self.assertEqual(execute.call_args.args[0],['docker','--context','colima','buildx','version'])

    def test_local_only_build_uses_buildkit_and_loads_result_without_push(self):
        execute=Mock()
        R.build_image('syd.ocir.io/ns/repo:v1','hash',prefix=['docker','--context','colima'],execute=execute)
        command=execute.call_args.args[0]
        self.assertEqual(command[:5],['docker','--context','colima','buildx','build'])
        self.assertIn('type=docker,oci-mediatypes=false',command);self.assertIn('--provenance=false',command);self.assertIn('linux/amd64',command)
        self.assertEqual(execute.call_count,1)

class PushFailureVerification(unittest.TestCase):
    def local(self,*,identity=D,revision='source'):
        return [{'Id':identity,'Architecture':'amd64','Os':'linux',
                 'Config':{'Labels':{'org.opencontainers.image.revision':revision}}}]

    def remote(self,*,digest='sha256:'+'b'*64,config=D):
        return {'Descriptor':{'digest':digest,'platform':{'architecture':'amd64','os':'linux'}},
                'OCIManifest':{'config':{'digest':config}}}

    def test_classic_config_and_containerd_manifest_identity(self):
        for remote in [self.remote(),self.remote(digest=D,config='sha256:'+'c'*64)]:
            execute=Mock(side_effect=[NS(stdout=json.dumps(self.local())),NS(stdout=json.dumps(remote))])
            self.assertEqual(R.confirm_published_image('registry/repo:tag','source',execute=execute),remote['Descriptor']['digest'])
            self.assertTrue(all('push' not in x.args[0] for x in execute.call_args_list))

    def test_different_image_unmatched_index_or_source_is_not_accepted(self):
        for local,remote in [(self.local(),self.remote(config='sha256:'+'c'*64)),
                             (self.local(revision='other'),self.remote())]:
            execute=Mock(side_effect=[NS(stdout=json.dumps(local)),NS(stdout=json.dumps(remote))])
            self.assertIsNone(R.confirm_published_image('registry/repo:tag','source',execute=execute))

    def test_ambiguous_push_recovers_only_with_matching_remote_identity(self):
        remote=self.remote()
        execute=Mock(side_effect=[NS(stdout='built'),subprocess.CalledProcessError(1,['docker','push'],stderr='manifest invalid'),
                                 NS(stdout=json.dumps(self.local())),NS(stdout=json.dumps(remote))])
        with patch.object(R,'source_hash',return_value='source'),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.build_push('registry/repo:tag','source',execute=execute),remote['Descriptor']['digest'])
        self.assertEqual(sum('push' in x.args[0] for x in execute.call_args_list),1)

    def test_failed_push_reports_category_without_sensitive_output(self):
        execute=Mock(side_effect=[NS(stdout='built'),
            subprocess.CalledProcessError(1,['docker','push'],stderr='unauthorized https://example.test/?token=PRIVATE_TOKEN'),
            subprocess.CalledProcessError(1,['docker','image','inspect'])])
        with patch.object(R,'source_hash',return_value='source'),self.assertRaisesRegex(ValueError,'authentication rejected') as caught:
            R.build_push('registry/repo:tag','source',execute=execute)
        self.assertNotIn('PRIVATE_TOKEN',str(caught.exception));self.assertNotIn('https://',str(caught.exception))
