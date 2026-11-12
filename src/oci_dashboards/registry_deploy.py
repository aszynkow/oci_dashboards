"""Two-stage OCIR bootstrap and image publication. Mutations are apply-only.

No Docker credentials are returned, persisted in receipts, or logged. Local
Docker/Colima context is used per command; global context is never switched.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')


def source_hash():
    files = [ROOT/'.dockerignore', *sorted((ROOT/'functions/coverage').glob('*')),
             *sorted((ROOT/'src/oci_dashboards').glob('*.py'))]
    digest = hashlib.sha256(b'coverage-linux-amd64-v1\0')
    for path in files:
        if path.is_file():
            digest.update(str(path.relative_to(ROOT)).encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def repository_compartment(config):
    """Follow the resolved dashboard compartment unless explicitly overridden."""
    return (config.get('coverage_repository_compartment_id') or config.get('dashboard_compartment_id')
            or config['telemetry_compartment_id'])


def bootstrap(config, output, *, existing_id=None):
    from .deploy import write_json
    folder = Path(output)/'ocir'
    identity = {'tenancy': config['iam_policy_compartment_id'], 'region': config['region'],
                'compartment': repository_compartment(config),
                'repository': config.get('coverage_repository_name', 'backup-coverage')}
    marker = folder/'deployment-identity.json'
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise ValueError('OCIR state belongs to another repository/scope; preserve state and review migration. To keep an existing repository compartment, explicitly set coverage_repository_compartment_id to its current compartment')
    write_json(marker, identity)
    owned_id = managed_repository(output)
    if owned_id and config.get('coverage_existing_repository_id') not in (None, owned_id):
        raise ValueError('Existing repository override conflicts with managed OCIR state')
    selected_existing = None if owned_id else (existing_id or config.get('coverage_existing_repository_id'))
    module = {'source': str(ROOT/'deploy/ocir'), 'oci_profile': config['oci_profile'],
              'region': identity['region'], 'tenancy_id': identity['tenancy'],
              'compartment_id': identity['compartment'], 'repository_name': identity['repository'],
              'existing_repository_id': selected_existing}
    write_json(folder/'terraform/main.tf.json', {
        'terraform': {'required_version': '>= 1.5.0', 'required_providers': {'oci': {'source': 'oracle/oci'}}},
        'module': {'registry': module}, 'output': {k: {'value': '${module.registry.'+k+'}'} for k in ('repository_id', 'namespace')}})
    write_json(folder/'build-intent.json', {'source_hash': source_hash(), 'tag': config.get('coverage_image_tag') or 'src-'+source_hash()[:24],
        'platform': 'linux/amd64', 'registry': config.get('coverage_registry_host') or 'derived from profile region',
        'namespace': 'discovered from tenancy', 'state': str(folder/'terraform/terraform.tfstate')})
    return folder


def managed_repository(output):
    state = Path(output)/'ocir/terraform/terraform.tfstate'
    if not state.exists():
        return None
    data = json.loads(state.read_text())
    ids = [i['attributes']['id'] for r in data.get('resources', [])
           if r.get('mode') != 'data' and r['type'] == 'oci_artifacts_container_repository'
           for i in r.get('instances', [])]
    if len(ids) > 1:
        raise ValueError('Ambiguous OCIR bootstrap state')
    return ids[0] if ids else None


class Registry:
    def __init__(self, config):
        import oci
        self.config = config
        sdk = oci.config.from_file(profile_name=config['oci_profile'])
        if sdk.get('tenancy') != config['iam_policy_compartment_id'] or sdk.get('region') != config['region']:
            raise ValueError('OCI profile changed after preparation; run deployment again')
        self.client = oci.artifacts.ArtifactsClient(sdk, timeout=(10,45))
        self.namespace = oci.object_storage.ObjectStorageClient(sdk, timeout=(10,45)).get_namespace(compartment_id=sdk['tenancy']).data
        host = config.get('coverage_registry_host')
        if not host:
            if oci.regions.REGION_REALMS.get(sdk['region']) != 'oc1':
                raise ValueError('Set coverage_registry_host to the documented OCIR hostname for this realm/region')
            keys = [k for k,v in oci.regions.REGIONS_SHORT_NAMES.items() if v == sdk['region']]
            if len(keys) != 1:
                raise ValueError('Cannot derive OCIR hostname; set coverage_registry_host')
            host = keys[0]+'.ocir.io'
        self.host = host
        self.compartment = repository_compartment(config)

    def repositories(self, name):
        # The SDK paginator flattens collection.items into Response.data (a list).
        import oci
        return oci.pagination.list_call_get_all_results(self.client.list_container_repositories,
            compartment_id=self.compartment, display_name=name).data

    def repository(self, name, existing_id=None):
        if existing_id:
            repo = self.client.get_container_repository(existing_id).data
            rows = [repo]
        else:
            rows = self.repositories(name)
        rows = [r for r in rows if r.display_name == name and r.compartment_id == self.compartment]
        if len(rows) > 1:
            raise ValueError('Multiple matching OCIR repositories; specify coverage_existing_repository_id')
        if existing_id and not rows:
            raise ValueError('Existing repository does not match selected name/compartment')
        if rows and (rows[0].is_public or rows[0].lifecycle_state != 'AVAILABLE'):
            raise ValueError('Coverage repository must be private and AVAILABLE')
        return rows[0] if rows else None

    def image_rows(self, repository_id, *, version=None, digest=None):
        import oci
        kwargs = {'repository_id': repository_id, 'lifecycle_state': 'AVAILABLE'}
        kwargs.update({'version': version} if version else {'image_digest': digest})
        rows = oci.pagination.list_call_get_all_results(self.client.list_container_images,
            compartment_id=self.compartment, **kwargs).data
        # API filtering is not a substitute for checking the exact returned identity.
        rows = [r for r in rows if r.repository_id == repository_id and r.lifecycle_state == 'AVAILABLE'
                and (r.version == version if version else r.digest == digest)]
        return rows

    def image(self, repository_id, *, version=None, digest=None):
        rows = self.image_rows(repository_id,version=version,digest=digest)
        digests = {r.digest for r in rows}
        if len(digests) > 1 or any(not DIGEST.fullmatch(d or '') for d in digests):
            raise ValueError('Ambiguous or invalid OCIR image digest')
        return next(iter(digests), None)

    def existing_image(self, uri):
        if not uri.startswith(self.host+'/'+self.namespace+'/'):
            raise ValueError('Existing image must use selected registry host and tenancy namespace; set coverage_registry_host if using another regional alias')
        path = uri[len(self.host+'/'+self.namespace+'/'):]
        requested_digest = None
        if '@' in path:
            path,requested_digest = path.rsplit('@',1)
            if not DIGEST.fullmatch(requested_digest):
                raise ValueError('Invalid existing image digest')
        if ':' in path:
            name,version = path.rsplit(':',1)
        else:
            name,version = path,None
        if not version and not requested_digest:
            raise ValueError('Existing image must have an explicit version or sha256 digest')
        repo = self.repository(name)
        resolved = self.image(repo.id,version=version,digest=requested_digest) if repo else None
        if not resolved or (requested_digest and resolved != requested_digest):
            raise ValueError('Existing coverage image was not found AVAILABLE with the requested digest in OCIR')
        if not version:
            # Functions requires a real tag even when imageDigest is supplied.
            rows = self.image_rows(repo.id,digest=resolved)
            tags = sorted({r.version for r in rows if r.version and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}',r.version)})
            if not tags:
                raise ValueError('Verified image has no usable tag; provide a tagged coverage_function_image')
            version = tags[0]
        return self.host+'/'+self.namespace+'/'+name+':'+version+'@'+resolved


def docker_prefix(context=None):
    if context and (context.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.-]+',context)):
        raise ValueError('Invalid Docker context name')
    return ['docker']+(['--context',context] if context else [])


def engine_ready(*, context=None, start_colima=False, execute=None):
    """Use an available Linux engine, optionally starting Colima explicitly."""
    from .deploy import run
    execute = execute or run
    prefix = docker_prefix(context)
    if not shutil.which('docker'):
        raise ValueError('Docker CLI is required; install Docker CLI and start Docker Desktop or Colima')
    try:
        result = execute(prefix+['info','--format','{{.OSType}}'],capture=True)
    except subprocess.CalledProcessError:
        if not start_colima:
            raise ValueError('Docker engine unavailable. Start Colima/Docker Desktop or use --start-colima --docker-context colima') from None
        if not shutil.which('colima'):
            raise ValueError('--start-colima requires the Colima CLI') from None
        execute(['colima','start','--runtime','docker'])
        prefix = docker_prefix(context or 'colima')
        result = execute(prefix+['info','--format','{{.OSType}}'],capture=True)
    if result.stdout.strip() != 'linux':
        raise ValueError('Coverage image build requires a Linux Docker engine')
    try:
        execute(prefix+['buildx','version'],capture=True)
    except subprocess.CalledProcessError:
        raise ValueError('Docker Buildx is required; install/register the plugin (macOS: brew install docker-buildx), then verify docker buildx version. Legacy builder fallback is disabled') from None
    return prefix


def docker_ready(host, *, context=None, start_colima=False, execute=None):
    """Check engine and credential configuration; never log credential values."""
    prefix = engine_ready(context=context,start_colima=start_colima,execute=execute)
    path = Path(os.environ.get('DOCKER_CONFIG',str(Path.home()/'.docker')))/'config.json'
    try:
        settings = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        settings = {}
    configured = (host in settings.get('auths', {}) or 'https://'+host in settings.get('auths', {})
                  or host in settings.get('credHelpers', {}) or bool(settings.get('credsStore')))
    if not configured:
        raise ValueError('No Docker credential configuration for '+host+'; run docker login '+host+' first')
    # A configured helper/store is not proof of server-side authentication or IAM.
    # Docker push performs that verification. No login/token generation is attempted.
    return prefix


def build_image(image, fingerprint, *, prefix=None, execute=None):
    from .deploy import run
    execute = execute or run
    prefix = prefix or ['docker']
    # Docker exporter auto-loads one image. Avoid default provenance/index
    # output: the Function needs only its linux/amd64 runnable manifest.
    execute(prefix+['buildx','build','--output','type=docker,oci-mediatypes=false',
        '--provenance=false','--progress=plain','--platform','linux/amd64',
        '--label','org.opencontainers.image.revision='+fingerprint,
        '-f',str(ROOT/'functions/coverage/Dockerfile'),'-t',image,str(ROOT)])


def push_error_category(error):
    """Report recognizable causes without echoing URLs, tokens or HTTP bodies."""
    content = ((error.stdout or '')+'\n'+(error.stderr or '')).lower()
    if 'certificate signed by unknown authority' in content:
        return 'TLS certificate chain is not trusted by the Docker engine'
    if 'x509:' in content or 'tls handshake' in content:
        return 'Docker engine TLS verification/handshake error'
    if 'no basic auth credentials' in content or 'unauthorized' in content or 'authentication required' in content:
        return 'registry authentication rejected or credentials missing; check docker login'
    if 'denied' in content or '403 forbidden' in content:
        return 'registry access denied; check login identity and repository push permission'
    if 'content digest' in content and 'not found' in content:
        return 'Docker engine content digest is missing'
    if 'manifest invalid' in content or 'manifest_invalid' in content:
        return 'registry rejected the image manifest'
    if any(value in content for value in ('timeout', 'connection refused', 'no such host')):
        return 'network connectivity, DNS or timeout error'
    return 'unclassified Docker push error (exit '+str(error.returncode)+')'


def local_image_identity(image, fingerprint, *, prefix=None, execute=None):
    from .deploy import run
    execute = execute or run
    prefix = prefix or ['docker']
    try:
        local = json.loads(execute(prefix+['image','inspect',image],capture=True).stdout)
        if not isinstance(local,list) or len(local) != 1:
            return None
        local = local[0]
        if (local.get('Architecture') != 'amd64' or local.get('Os') != 'linux'
                or local.get('Config',{}).get('Labels',{}).get('org.opencontainers.image.revision') != fingerprint
                or not DIGEST.fullmatch(local.get('Id',''))):
            return None
        return local['Id']
    except (subprocess.CalledProcessError, ValueError, TypeError, AttributeError):
        return None


def confirm_published_image(image, fingerprint, *, prefix=None, execute=None, expected_image_id=None):
    """Bind remote manifest to this local build or its durable build checkpoint."""
    from .deploy import run
    execute = execute or run
    prefix = prefix or ['docker']
    identity = expected_image_id or local_image_identity(image,fingerprint,prefix=prefix,execute=execute)
    if not identity or not DIGEST.fullmatch(identity):
        return None
    try:
        remote = json.loads(execute(prefix+['manifest','inspect','--verbose',image],capture=True).stdout)
        if not isinstance(remote,dict):
            return None
        manifest = remote.get('OCIManifest') or remote.get('SchemaV2Manifest') or {}
        descriptor = remote.get('Descriptor') or {}
        digest = descriptor.get('digest','')
        identity_matches = digest == identity or manifest.get('config',{}).get('digest') == identity
        if not identity_matches or not DIGEST.fullmatch(digest):
            return None
        platform = descriptor.get('platform') or {}
        if platform and (platform.get('architecture') != 'amd64' or platform.get('os') != 'linux'):
            return None
        return digest
    except (subprocess.CalledProcessError, ValueError, TypeError, KeyError, AttributeError):
        return None


def build_push(image, fingerprint, *, prefix=None, execute=None, checkpoint=None):
    from .deploy import run
    execute = execute or run
    prefix = prefix or ['docker']
    cached = local_image_identity(image,fingerprint,prefix=prefix,execute=execute) if checkpoint else None
    expected = checkpoint.record.get('local_image_id') if checkpoint else None
    if checkpoint and checkpoint.record['phase'] == 'pushing' and cached != expected:
        raise ValueError('Interrupted push local image is missing or changed; restore the recorded image or use a new image tag')
    reusable = cached and (not expected or cached == expected)
    if not reusable:
        if checkpoint:
            checkpoint.save('building',local_image_id=None,digest=None)
        build_image(image,fingerprint,prefix=prefix,execute=execute)
        if checkpoint:
            cached = local_image_identity(image,fingerprint,prefix=prefix,execute=execute)
            if not cached:
                raise ValueError('Built image source/platform identity could not be verified; no push attempted')
    elif checkpoint:
        print('Resuming image publication: verified local build; skipping rebuild.',flush=True)
    if source_hash() != fingerprint:
        raise ValueError('Coverage source changed during image build; no image pushed. Run deployment again')
    if checkpoint:
        checkpoint.save('built',local_image_id=cached,digest=None)
        checkpoint.save('pushing')
    try:
        pushed = execute(prefix+['push',image],capture=True)
    except subprocess.CalledProcessError as error:
        digest = confirm_published_image(image,fingerprint,prefix=prefix,execute=execute)
        if digest:
            print('Docker push reported an error, but the remote manifest matches the local source-labelled linux/amd64 image. Verifying its digest with OCI before deployment.',flush=True)
            return digest
        raise ValueError('Docker push failed: '+push_error_category(error)+'. Remote publication could not be verified; repository/state are retained and Function deployment stopped') from None
    digests = set(re.findall(r'digest:\s*(sha256:[0-9a-f]{64})',pushed.stdout or ''))
    if len(digests) != 1:
        raise ValueError('Docker push did not return one unambiguous manifest digest; inspect registry before retrying')
    return digests.pop()


def image_receipt_matches(path, *, fingerprint, uri, digest):
    if not path.exists():
        return False
    receipt = json.loads(path.read_text())
    return all(receipt.get(k) == v for k,v in {'source_hash':fingerprint, 'tag_uri':uri, 'digest':digest}.items())


def wait_for_digest(registry, repository_id, tag, expected):
    for attempt in range(6):
        digest = registry.image(repository_id,version=tag)
        if digest:
            if digest != expected:
                raise ValueError('OCIR tag digest differs from the recorded push; refusing Function deployment')
            return digest
        if attempt < 5:
            time.sleep(2)
    raise ValueError('OCIR digest is not yet visible; pushed checkpoint retained. Rerun to verify publication without rebuilding or repushing')


def resolve(config, output, *, apply=False, context=None, start_colima=False, before_publication=None):
    """Plan bootstrap; resume verified build/publication phases on apply only."""
    from .deploy import plan_stack, run, write_json
    from .image_checkpoint import ImageCheckpoint
    registry = Registry(config)
    if config.get('coverage_function_image'):
        return registry.existing_image(config['coverage_function_image'])
    fingerprint = source_hash()
    name = config['coverage_repository_name']
    owned_id = managed_repository(output)
    explicit_id = config.get('coverage_existing_repository_id')
    if owned_id and explicit_id and owned_id != explicit_id:
        raise ValueError('Existing repository override conflicts with the managed OCIR state')
    repo = registry.repository(name,explicit_id or owned_id)
    existing_id = None if owned_id else (repo.id if repo else explicit_id)
    folder = bootstrap(config,output,existing_id=existing_id)
    prefix = plan_stack(folder)
    tag = config.get('coverage_image_tag') or 'src-'+fingerprint[:24]
    uri = registry.host+'/'+registry.namespace+'/'+name+':'+tag
    checkpoint = ImageCheckpoint(output,{
        'source_hash':fingerprint,'tag_uri':uri,'platform':'linux/amd64',
        'tenancy':config['iam_policy_compartment_id'],'region':config['region'],
        'repository_compartment':repository_compartment(config)})
    saved_repository = checkpoint.record.get('repository_id')
    if saved_repository and (not repo or repo.id != saved_repository):
        raise ValueError('Image checkpoint repository is missing or changed; refusing replacement/publication')
    digest = registry.image(repo.id,version=tag) if repo else None
    receipt_path = Path(output)/'coverage-image.json'
    recorded = checkpoint.record.get('digest')
    if recorded and digest and recorded != digest:
        raise ValueError('OCIR tag no longer matches its durable image checkpoint; refusing overwrite/deployment')
    verified = bool(digest and (image_receipt_matches(receipt_path,fingerprint=fingerprint,uri=uri,digest=digest)
                               or recorded == digest))
    recoverable = bool(checkpoint.record.get('local_image_id'))
    if digest and not verified and not recoverable:
        raise ValueError('OCIR tag already exists without a matching source/digest receipt or build checkpoint. Use coverage_function_image to explicitly reuse it, or choose a new coverage_image_tag; existing tags are never overwritten')
    if not apply:
        write_json(folder/'publication-status.json',{'image':uri,'source_hash':fingerprint,
            'verified_digest':digest if verified else None,'checkpoint_phase':checkpoint.record['phase'],
            'checkpoint_file':str(checkpoint.path),
            'pending':[] if verified else ['resume/verify image publication','generate final dashboard plan']})
        return uri+'@'+digest if verified else None

    print('Image checkpoint: '+str(checkpoint.path)+' (phase: '+checkpoint.record['phase']+')',flush=True)
    # A pushed digest is durable evidence of the completed push. OCI validation
    # alone can finish it even if the engine/image cache or final receipt is gone.
    if recorded and not digest:
        if not repo or checkpoint.record.get('repository_id') not in (None,repo.id):
            raise ValueError('Recorded publication repository is missing or changed; checkpoint retained')
        digest = wait_for_digest(registry,repo.id,tag,recorded)
        verified = True
    # The process may have stopped after the remote commit but before recording
    # Docker's result. Verify it against the persisted local build ID, no repush.
    if digest and not verified and recoverable:
        confirmed = confirm_published_image(uri,fingerprint,prefix=docker_prefix(context),
            expected_image_id=checkpoint.record['local_image_id'])
        if confirmed != digest:
            raise ValueError('Existing OCIR tag cannot be tied to the build checkpoint; refusing overwrite/deployment')
        verified = True
        print('Resuming publication: remote manifest matches the saved build; no rebuild or push needed.',flush=True)
    if not verified and before_publication:
        before_publication(uri)
    docker = None if verified else docker_ready(registry.host,context=context,start_colima=start_colima)
    if not verified:
        checkpoint.save(checkpoint.record['phase'])
    run(prefix+['apply','-input=false','deployment.tfplan'])
    outputs = json.loads(run(prefix+['output','-json'],capture=True).stdout)
    repository_id = outputs['repository_id']['value']
    if outputs['namespace']['value'] != registry.namespace or (repo and repo.id != repository_id):
        raise ValueError('OCIR repository identity/namespace changed during apply; image publication stopped')
    if checkpoint.record.get('repository_id') not in (None,repository_id):
        raise ValueError('Repository no longer matches the image checkpoint')
    if not verified:
        checkpoint.save(checkpoint.record['phase'],repository_id=repository_id)
        pushed = build_push(uri,fingerprint,prefix=docker,checkpoint=checkpoint)
        # Commit immediately, before the potentially delayed OCI list response.
        checkpoint.save('pushed',digest=pushed,repository_id=repository_id)
        digest = wait_for_digest(registry,repository_id,tag,pushed)
    checkpoint.save('published',digest=digest,repository_id=repository_id)
    write_json(receipt_path,{'source_hash':fingerprint,'tag_uri':uri,'digest':digest,'repository_id':repository_id,
        'platform':'linux/amd64','image_uri':uri+'@'+digest})
    return uri+'@'+digest
