"""Optional deployment integration using real Terraform tfvars parsing, offline."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from oci_dashboards.deploy import ROOT,load_tfvars_settings,prepare,preflight


@unittest.skipUnless(shutil.which('terraform'),'Terraform required')
class CoverageDeployment(unittest.TestCase):
    def settings(self,path):
        with patch('oci.config.from_file',return_value={'region':'ap-sydney-1','tenancy':'ocid1.tenancy.oc1..PROFILE'}):
            return load_tfvars_settings(path,profile='TEST')

    def test_disabled_default_keeps_activity_stack_and_dashboard_unchanged(self):
        config=self.settings(ROOT/'terraform/terraform.tfvars.example')
        self.assertFalse(config['enable_coverage'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);prepare(config,path)
            stack=json.loads((path/'terraform/main.tf.json').read_text())
            self.assertNotIn('enable_coverage',stack['module']['central'])
            self.assertNotIn('coverage_runtime_log_id',stack['output'])
            self.assertFalse((path/'coverage-schema.json').exists())
            self.assertEqual(len(json.loads((path/'dashboard.management.json').read_text())['dashboards']),1)

    def test_enabled_generates_separate_schema_dashboard_and_reuses_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);tfvars=path/'coverage.tfvars'
            tfvars.write_text((ROOT/'terraform/terraform.tfvars.example').read_text()+
                '\nenable_coverage=true\ncoverage_subnet_ids=["ocid1.subnet.oc1.ap-sydney-1.TEST"]\ncoverage_function_image="syd.ocir.io/sample/coverage:v1"\n')
            config=self.settings(tfvars);summary=prepare(config,path/'out')
            stack=json.loads((path/'out/terraform/main.tf.json').read_text())
            central=stack['module']['central']
            self.assertEqual(stack['output']['coverage_runtime_log_id']['value'],
                             '${module.central.coverage_runtime_log_id}')
            self.assertIn('coverage_runtime_log_group_id',stack['output'])
            self.assertTrue(central['enable_coverage'])
            self.assertEqual(summary['coverage']['widgets'],16)
            self.assertEqual(summary['coverage']['compartments'],config['inventory_compartment_ids'])
            self.assertEqual(summary['coverage']['regions'],['ap-sydney-1'])
            self.assertTrue((path/'out/coverage.management.api.json').exists())
            definition=json.loads((path/'out/coverage-schema.json').read_text())
            self.assertEqual(central['coverage_source_name'],definition['source'])
            self.assertNotEqual(definition['source'],json.loads((path/'out/native-event-schema.json').read_text())['source'])
            with self.assertRaisesRegex(ValueError,'placeholder'):preflight(config)

    def test_missing_function_prerequisites_fail_before_prepare(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'coverage.tfvars'
            path.write_text((ROOT/'terraform/terraform.tfvars.example').read_text()+'\nenable_coverage=true\n')
            with self.assertRaisesRegex(ValueError,'requires coverage_subnet_ids'):self.settings(path)

    def test_subhour_schedule_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'coverage.tfvars'
            path.write_text((ROOT/'terraform/terraform.tfvars.example').read_text()+'\ncoverage_schedule="*/15 * * * *"\n')
            with self.assertRaises(ValueError):self.settings(path)

class FunctionsImageContract(unittest.TestCase):
    def test_verified_tag_and_digest_are_separate_in_terraform_and_sdk_payload(self):
        import oci
        from oci_dashboards.deploy import terraform_stack
        digest='sha256:'+'a'*64
        with patch('oci.config.from_file',return_value={'region':'ap-sydney-1','tenancy':'ocid1.tenancy.oc1..TEST'}):
            config=load_tfvars_settings(ROOT/'terraform/terraform.tfvars.example',profile='TEST')
        config.update(enable_coverage=True,coverage_function_image='syd.ocir.io/ns/backup-coverage:version@'+digest,
                      coverage_subnet_ids=['subnet'])
        central=terraform_stack(config,Path('/tmp/generated'))['module']['central']
        self.assertEqual(central['coverage_function_image'],'syd.ocir.io/ns/backup-coverage:version')
        self.assertEqual(central['coverage_function_image_digest'],digest)
        model=oci.functions.models.CreateContainerImageFunctionSourceDetails(
            image=central['coverage_function_image'],image_digest=central['coverage_function_image_digest'])
        serializer=object.__new__(oci.base_client.BaseClient);serializer.complex_type_mappings=vars(oci.functions.models)
        body=serializer.sanitize_for_serialization(model)
        self.assertEqual(body['image'],'syd.ocir.io/ns/backup-coverage:version')
        self.assertEqual(body['imageDigest'],digest);self.assertNotIn('@',body['image'])

    def test_digest_only_input_is_deferred_until_real_tag_discovery(self):
        from oci_dashboards.deploy import function_image_arguments
        self.assertEqual(function_image_arguments('syd.ocir.io/ns/repo@sha256:'+'a'*64),(None,None))
        with self.assertRaises(ValueError):function_image_arguments('syd.ocir.io/ns/repo:v1@invalid')

    def test_existing_digest_override_resolves_actual_tag_and_rejects_drift(self):
        from unittest.mock import Mock
        from types import SimpleNamespace as NS
        from oci_dashboards.registry_deploy import Registry
        digest='sha256:'+'a'*64
        registry=object.__new__(Registry);registry.host='syd.ocir.io';registry.namespace='ns'
        registry.repository=Mock(return_value=NS(id='repo'))
        registry.image=Mock(return_value=digest);registry.image_rows=Mock(return_value=[NS(version='v2')])
        self.assertEqual(registry.existing_image('syd.ocir.io/ns/repo@'+digest),'syd.ocir.io/ns/repo:v2@'+digest)
        registry.image.return_value='sha256:'+'b'*64
        with self.assertRaisesRegex(ValueError,'requested digest'):
            registry.existing_image('syd.ocir.io/ns/repo:v2@'+digest)
