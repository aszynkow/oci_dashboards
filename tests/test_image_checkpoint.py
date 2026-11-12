"""Crash/restart tests for non-Terraform stages. No Docker/OCI calls are made."""
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
from oci_dashboards.image_checkpoint import ImageCheckpoint

FP='f'*64
LOCAL='sha256:'+'1'*64
PUBLISHED='sha256:'+'2'*64
OTHER='sha256:'+'3'*64
CFG={'scope_id':'test','oci_profile':'TEST','region':'ap-sydney-1','iam_policy_compartment_id':'tenancy',
     'dashboard_compartment_id':'dashboard','telemetry_compartment_id':'telemetry','coverage_repository_name':'backup-coverage'}
URI='syd.ocir.io/ns/backup-coverage:src-'+FP[:24]
IDENTITY={'source_hash':FP,'tag_uri':URI,'platform':'linux/amd64','tenancy':'tenancy',
          'region':'ap-sydney-1','repository_compartment':'dashboard'}


class FakeRuntime:
    def __init__(self):
        self.local=None;self.remote=None;self.builds=0;self.pushes=0;self.docker_reads=0
        self.failure=None;self.oci_failure=False
        self.registry=NS(host='syd.ocir.io',namespace='ns',repository=Mock(return_value=NS(id='repo')),
                         image=self.image)
    def image(self,*args,**kwargs):
        if self.oci_failure and self.remote:
            self.oci_failure=False
            raise RuntimeError('OCI list interrupted')
        return self.remote
    def execute(self,command,**kwargs):
        if command[0]=='terraform':
            return NS(stdout=json.dumps({'repository_id':{'value':'repo'},'namespace':{'value':'ns'}}))
        if 'build' in command:
            self.builds+=1;self.local=LOCAL
            if self.failure=='build-interrupted':
                self.failure=None;raise KeyboardInterrupt()
            return NS(stdout='built')
        if 'push' in command:
            self.pushes+=1
            if self.failure=='denied':
                raise subprocess.CalledProcessError(1,command,stderr='denied: requested access')
            self.remote=PUBLISHED
            if self.failure=='push-interrupted':
                self.failure=None;raise KeyboardInterrupt()
            return NS(stdout='digest: '+PUBLISHED)
        self.docker_reads+=1
        if 'manifest' in command:
            if not self.remote:raise subprocess.CalledProcessError(1,command,stderr='manifest unknown')
            return NS(stdout=json.dumps({'Descriptor':{'digest':self.remote,'platform':{'architecture':'amd64','os':'linux'}},
                                        'OCIManifest':{'config':{'digest':LOCAL}}}))
        if 'inspect' in command:
            if not self.local:raise subprocess.CalledProcessError(1,command,stderr='image missing')
            return NS(stdout=json.dumps([{'Id':self.local,'Architecture':'amd64','Os':'linux',
                'Config':{'Labels':{'org.opencontainers.image.revision':FP}}}]))
        raise AssertionError(command)


class CrashResume(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name);self.runtime=FakeRuntime()
        patches=[patch.object(R,'source_hash',return_value=FP),patch.object(R,'Registry',return_value=self.runtime.registry),
                 patch('oci_dashboards.deploy.plan_stack',return_value=['terraform']),
                 patch('oci_dashboards.deploy.run',side_effect=self.runtime.execute),
                 patch.object(R,'docker_ready',return_value=['docker'])]
        for p in patches:
            value=p.start();self.addCleanup(p.stop)
            if p.attribute=='docker_ready':self.engine=value
    def resolve(self,apply=True):
        with contextlib.redirect_stdout(io.StringIO()):return R.resolve(CFG,self.out,apply=apply)
    def checkpoint(self):return ImageCheckpoint(self.out,IDENTITY)

    def test_push_failure_reuses_verified_local_build_on_restart(self):
        self.runtime.failure='denied'
        with self.assertRaisesRegex(ValueError,'access denied'):self.resolve()
        self.assertEqual(self.checkpoint().record['phase'],'pushing')
        self.assertEqual(self.runtime.builds,1)
        self.runtime.failure=None
        self.assertTrue(self.resolve().endswith('@'+PUBLISHED))
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,2)
        self.assertEqual(self.checkpoint().record['phase'],'published')

    def test_build_completed_before_checkpoint_can_be_adopted_locally(self):
        self.runtime.failure='build-interrupted'
        with self.assertRaises(KeyboardInterrupt):self.resolve()
        self.assertEqual(self.checkpoint().record['phase'],'building')
        self.resolve()
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,1)

    def test_push_commit_before_digest_record_recovers_without_engine_or_local_cache(self):
        self.runtime.failure='push-interrupted'
        with self.assertRaises(KeyboardInterrupt):self.resolve()
        self.assertEqual(self.checkpoint().record['phase'],'pushing')
        self.runtime.local=None
        self.engine.reset_mock()
        self.resolve()
        self.engine.assert_not_called()
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,1)
        self.assertTrue((self.out/'coverage-image.json').exists())

    def test_oci_verification_failure_after_push_resumes_without_docker(self):
        self.runtime.oci_failure=True
        with self.assertRaisesRegex(RuntimeError,'OCI list interrupted'):self.resolve()
        self.assertEqual(self.checkpoint().record['phase'],'pushed')
        self.assertFalse((self.out/'coverage-image.json').exists())
        reads=self.runtime.docker_reads;self.runtime.local=None;self.engine.reset_mock()
        self.resolve()
        self.engine.assert_not_called();self.assertEqual(reads,self.runtime.docker_reads)
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,1)

    def test_published_checkpoint_recovers_deleted_receipt_and_plan_is_read_only(self):
        self.resolve();(self.out/'coverage-image.json').unlink()
        before=self.checkpoint().path.read_bytes();reads=self.runtime.docker_reads
        self.assertTrue(self.resolve(apply=False).endswith('@'+PUBLISHED))
        self.assertEqual(before,self.checkpoint().path.read_bytes())
        self.assertFalse((self.out/'coverage-image.json').exists())
        self.resolve()
        self.assertEqual(self.runtime.docker_reads,reads)
        self.assertEqual(self.runtime.pushes,1);self.assertTrue((self.out/'coverage-image.json').exists())

    def test_completed_build_with_evicted_local_cache_rebuilds_before_first_push(self):
        self.checkpoint().save('built',local_image_id=LOCAL,repository_id='repo')
        self.resolve()
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,1)
        self.assertEqual(self.checkpoint().record['phase'],'published')

    def test_unrecorded_push_digest_plan_defers_recovery_without_docker(self):
        self.runtime.failure='push-interrupted'
        with self.assertRaises(KeyboardInterrupt):self.resolve()
        before=self.checkpoint().path.read_bytes();reads=self.runtime.docker_reads
        self.assertIsNone(self.resolve(apply=False))
        self.assertEqual(before,self.checkpoint().path.read_bytes())
        self.assertEqual(reads,self.runtime.docker_reads)

    def test_remote_digest_drift_is_not_overwritten(self):
        self.resolve();self.runtime.remote=OTHER
        with self.assertRaisesRegex(ValueError,'no longer matches'):self.resolve()
        self.assertEqual(self.runtime.pushes,1)

    def test_interrupted_push_replaced_local_image_is_not_rebuilt_or_pushed(self):
        self.runtime.failure='denied'
        with self.assertRaises(ValueError):self.resolve()
        self.runtime.local=OTHER;self.runtime.failure=None
        with self.assertRaisesRegex(ValueError,'local image is missing or changed'):self.resolve()
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,1)

    def test_pushed_checkpoint_waits_for_registry_visibility_without_republishing(self):
        self.runtime.oci_failure=True
        with self.assertRaises(RuntimeError):self.resolve()
        self.runtime.remote=None
        with patch.object(R.time,'sleep'),self.assertRaisesRegex(ValueError,'without rebuilding or repushing'):self.resolve()
        self.assertEqual(self.checkpoint().record['phase'],'pushed')
        self.assertEqual(self.runtime.builds,1);self.assertEqual(self.runtime.pushes,1)


class CheckpointStorage(unittest.TestCase):
    def test_private_atomic_storage_and_source_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            cp=ImageCheckpoint(folder,IDENTITY)
            self.assertFalse(cp.path.exists())
            cp.save('built',local_image_id=LOCAL)
            self.assertEqual(cp.path.stat().st_mode & 0o777,0o600)
            self.assertEqual(cp.path.parent.stat().st_mode & 0o777,0o700)
            self.assertFalse(list(cp.path.parent.glob('*.tmp')))
            changed=ImageCheckpoint(folder,{**IDENTITY,'source_hash':'changed'})
            self.assertNotEqual(cp.path,changed.path);self.assertFalse(changed.path.exists())
            self.assertEqual(ImageCheckpoint(folder,IDENTITY).record['local_image_id'],LOCAL)

    def test_corrupt_identity_or_digest_does_not_resume(self):
        for change in [{'version':2},{'identity':{}},{'local_image_id':'invalid'},{'phase':'published'},[]]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                cp=ImageCheckpoint(folder,IDENTITY);cp.save('built',local_image_id=LOCAL)
                cp.path.write_text(json.dumps({**cp.record,**change} if isinstance(change,dict) else change))
                with self.assertRaises(ValueError):ImageCheckpoint(folder,IDENTITY)
