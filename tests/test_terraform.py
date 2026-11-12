"""Provider-free Terraform expression checks plus SDK resource contract checks."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from oci_dashboards.deploy import ROOT
from oci_dashboards.events import SUPPORTED


class TerraformNativeTests(unittest.TestCase):
    def test_activity_has_no_compute_functions_or_dynamic_groups_and_coverage_is_optional(self):
        text='\n'.join(path.read_text() for path in (ROOT/'terraform').rglob('*.tf') if path.name != 'coverage.tf')
        for forbidden in ('oci_functions_','oci_core_instance','oci_resource_scheduler_','oci_identity_dynamic_group',
                          'oci_objectstorage_bucket','custom_block_backup_health'):
            self.assertNotIn(forbidden,text)
        for path in (ROOT/'terraform').rglob('*.tf'):
            for match in re.finditer(r'resource "oci_identity_[^"]+" "[^"]+" \{',path.read_text()):
                self.assertRegex(path.read_text()[match.end():].split('\n}',1)[0],r'provider\s*=\s*oci.home')

    def test_native_event_types_exact_compartment_rules_and_connector_contract(self):
        events=(ROOT/'terraform/events.tf').read_text()
        for kind in SUPPORTED:self.assertIn(kind,events)
        self.assertIn('compartmentId = [each.value]',events)
        self.assertNotIn('operationSucceed',events) # unknown statuses are collected too.
        analytics=(ROOT/'terraform/analytics.tf').read_text()
        for clause in ('kind      = "streaming"','kind                  = "loggingAnalytics"',
                       'log_source_identifier = var.native_source_name','TRIM_HORIZON'):
            self.assertIn(clause,analytics)
        self.assertNotIn('tasks {',analytics)
        self.assertIn('request.principal.type=\'eventrule\'',events)
        self.assertIn('STREAM_CONSUME',analytics)
        self.assertIn('LOG_ANALYTICS_LOG_GROUP_UPLOAD_LOGS',analytics)
        self.assertNotIn('manage stream-family',events+analytics)

    def test_reused_stream_is_a_data_source_and_policy_uses_its_real_compartment(self):
        events=(ROOT/'terraform/events.tf').read_text()
        self.assertIn('count              = var.existing_stream_id == null ? 1 : 0',events)
        self.assertIn('data "oci_streaming_stream" "existing"',events)
        self.assertIn('data.oci_streaming_stream.existing[0].compartment_id',events)
        self.assertIn('moved {',events)
        self.assertIn('from = oci_streaming_stream.events',events)
        self.assertIn('local.events_stream_compartment_id',events)
        analytics=(ROOT/'terraform/analytics.tf').read_text()
        self.assertIn('local.events_stream_compartment_id',analytics)
        self.assertNotIn('oci_streaming_stream.events.id',analytics)

    def test_tf_has_no_executable_provisioners_and_legacy_marker_is_inert(self):
        text='\n'.join(path.read_text() for path in (ROOT/'terraform').rglob('*.tf'))
        self.assertNotIn('provisioner "',text)
        self.assertNotIn('BH_INSTALLER',text)
        self.assertNotIn('native_schema_installer',text)
        analytics=(ROOT/'terraform/analytics.tf').read_text()
        self.assertIn('resource "terraform_data" "native_schema"',analytics)
        self.assertNotIn('triggers_replace',analytics)
        self.assertNotIn('depends_on = [terraform_data.native_schema',analytics)

    @unittest.skipUnless(shutil.which('terraform'),'Terraform required')
    def test_discovered_home_expression_selects_actual_home_and_fails_closed(self):
        text=(ROOT/'terraform/providers.tf').read_text()
        expression=' '.join(text.split('var.home_region : ',1)[1].split('\n}',1)[0].split())
        for rows,expected in [([{'region_name':'ap-sydney-1','is_home_region':False},
                               {'region_name':'us-ashburn-1','is_home_region':True}],'us-ashburn-1'),([],None),
                              ([{'region_name':r,'is_home_region':True} for r in ('a','b')],None)]:
            expr=expression.replace('data.oci_identity_region_subscriptions.tenancy.region_subscriptions',
                                    'jsondecode('+json.dumps(json.dumps(rows))+')')
            with tempfile.TemporaryDirectory() as folder:
                result=subprocess.run([shutil.which('terraform'),'-chdir='+folder,'console','-no-color'],
                    input=expr+'\n',text=True,capture_output=True,
                    env={k:v for k,v in os.environ.items() if not k.startswith(('TF_VAR_','TF_CLI_ARGS','TF_LOG'))})
            self.assertEqual(result.returncode==0,expected is not None,result.stderr)
            if expected:self.assertEqual(json.loads(result.stdout),expected)
