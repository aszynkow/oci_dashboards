"""Resource-principal inventory collection, bounded LA uploads and derived metrics."""
import json
import uuid
from datetime import datetime, timezone
from .coverage import collect, metrics, instant
from .coverage_dashboard import names


def diagnostic(event, **fields):
    """Bounded metadata only: never log config, payloads or raw SDK exceptions."""
    print(json.dumps({'event': event, 'time': datetime.now(timezone.utc).isoformat(),
                      **fields}, separators=(',', ':')), flush=True)


def log_payload(records, source):
    return json.dumps({'logEvents':[{'logSourceName':source, 'logPath':'backup-coverage.json',
                                    'logRecords':[json.dumps(r,separators=(',',':')) for r in records]}]},separators=(',',':')).encode()


def batches(records, source, limit=1500000):
    batch=[]
    for row in records:
        if len(log_payload([row],source))>limit:
            raise ValueError('Coverage record exceeds upload limit')
        if batch and len(log_payload([*batch,row],source))>limit:
            yield batch;batch=[]
        batch.append(row)
    if batch:yield batch


def publish_logs(client, namespace, group, scope, records):
    # Publish summary last. Every row carries ExpectedRecords; dashboard rejects
    # an incompletely uploaded/indexed run even if a request fails mid-run.
    source=names(scope)['source']
    def upload(batch, summary):
        result = client.upload_log_events_file(
            namespace, group, log_payload(batch, source), payload_type='JSON',
            content_type='application/octet-stream')
        diagnostic('coverage.upload.accepted', run_id=records[-1]['RunID'],
                   records=len(batch), summary=summary,
                   opc_request_id=result.headers.get('opc-request-id'))
    for batch in batches(records[:-1],source):
        upload(batch, False)
    upload(records[-1:], True)


def publish_metrics(client, config, records):
    import oci
    M=oci.monitoring.models
    summary=records[-1]
    details=M.PostMetricDataDetails(metric_data=[M.MetricDataDetails(
        namespace='backup_coverage', name=name, compartment_id=config['telemetry_compartment_id'],
        dimensions={'scope':config['scope_id'],'collectorRegion':config['region']},
        datapoints=[M.Datapoint(timestamp=instant(summary['eventTime']),value=value)])
        for name,value in metrics(records).items()])
    result=client.post_metric_data(details)
    if result.data.failed_metrics_count:
        raise RuntimeError('OCI Monitoring rejected derived coverage metrics')


def run(config):
    import oci
    run_id = str(uuid.uuid4())
    stage = 'authentication'
    diagnostic('coverage.started', run_id=run_id)
    try:
        signer=oci.auth.signers.get_resource_principals_signer()
        opts={'signer':signer,'timeout':(10,45)}
        def factory(region):return oci.core.BlockstorageClient({'region':region},**opts)
        stage = 'inventory'
        diagnostic('coverage.inventory.started', run_id=run_id,
                   compartments=len(config['inventory_compartment_ids']),
                   regions=len(config.get('coverage_regions') or [config['region']]))
        records=collect(factory,config,run_id=run_id)
        summary=records[-1]
        diagnostic('coverage.inventory.completed', run_id=run_id, records=len(records),
                   observed_volumes=summary['Total'], scope_state=summary['ScopeState'],
                   errors=summary['ErrorCount'])
        stage = 'log_upload'
        diagnostic('coverage.upload.started', run_id=run_id)
        la=oci.log_analytics.LogAnalyticsClient({'region':config['region']},**opts)
        publish_logs(la,config['log_analytics_namespace'],config['coverage_log_group_id'],config['scope_id'],records)
        stage = 'metrics'
        diagnostic('coverage.metrics.started', run_id=run_id)
        # Ingestion endpoint differs from Monitoring query endpoint.
        # SDK derives realm-specific endpoints using the selected region.
        monitoring=oci.monitoring.MonitoringClient({'region':config['region']},**opts)
        monitoring.base_client.set_region(config['region'])
        endpoint=monitoring.base_client.endpoint.replace('://telemetry.','://telemetry-ingestion.')
        monitoring.base_client.endpoint=endpoint
        publish_metrics(monitoring,config,records)
        diagnostic('coverage.completed', run_id=run_id, scope_state=summary['ScopeState'],
                   observed_volumes=summary['Total'], errors=summary['ErrorCount'])
        return {'run_id':run_id,'observed_volumes':summary['Total'],'scope_state':summary['ScopeState']}
    except Exception as exc:
        diagnostic('coverage.failed', run_id=run_id, stage=stage,
                   error_type=type(exc).__name__, status=getattr(exc, 'status', None),
                   code=getattr(exc, 'code', None),
                   opc_request_id=getattr(exc, 'request_id', None))
        raise
