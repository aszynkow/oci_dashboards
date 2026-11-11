import json
import base64
from copy import deepcopy
import unittest
from oci_dashboards.config import load
from oci_dashboards.deploy import ROOT
from oci_dashboards.management import build, api_payload, widgets, validate, PREVIEW
from oci_dashboards.events import names, CREATE, COPY
import oci


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.config = load(ROOT/'config/backup-health.example.json')
        self.payload = build(self.config)
        self.dashboard = self.payload['dashboards'][0]

    def test_all_15_widgets_have_resolved_native_references_and_no_overlap(self):
        searches = {s['id']:s for s in self.dashboard['saved-searches']}
        self.assertEqual(len(searches),15)
        cells = set()
        for tile in self.dashboard['tiles']:
            self.assertIn(tile['saved-search-id'], searches)
            for row in range(tile['row'],tile['row']+tile['height']):
                for col in range(tile['column'],tile['column']+tile['width']):
                    self.assertNotIn((row,col),cells)
                    cells.add((row,col))
        self.assertFalse(self.dashboard['ui-config']['isTimeRangeEnabled'])

    def test_queries_use_native_indexed_fields_and_scoped_source_and_group(self):
        identity=names(self.config['scope_id'])
        for item in widgets(self.config):
            self.assertIn(identity['display'],item['query'])
            self.assertIn('__BH_ANALYTICS_LOG_GROUP_ID__',item['query'])
            self.assertIn(identity['label_prefix']+'EventID',item['query'])
            self.assertIn(CREATE,item['query'])
            self.assertIn(COPY,item['query'])
            for forbidden in ('collection_health','volume_snapshot','custom_block_backup_health', 'jsonextract'):
                self.assertNotIn(forbidden,item['query'])
        for title in ('Recovery targets met','No assigned policy','Required cross region','Monitored volumes'):
            self.assertNotIn(title,json.dumps(self.payload))

    def test_all_widget_scopes_use_filter_array_and_telemetry_compartment(self):
        for search in self.dashboard['saved-searches']:
            scope=search['ui-config']['scopeFilters']
            self.assertIs(scope['isGlobal'],False)
            filters={f['type']:f for f in scope['filters']}
            self.assertEqual(set(filters),{'LogGroup','Entity','LogSet','Region'})
            self.assertEqual(filters['LogGroup']['values'][0]['value'],self.config['telemetry_compartment_id'])
            self.assertIs(filters['LogGroup']['flags']['IncludeSubCompartments'],False)
            self.assertEqual(filters['Entity']['values'],[])
            self.assertEqual(filters['LogSet']['values'],[])
            self.assertEqual(filters['Region']['values'][0]['value'],self.config['region'])
            self.assertNotIn('LogGroup',scope)  # No stale keyed alias competing with filters[].

    def test_original_missing_array_and_wrong_identifier_fail_generation_validation(self):
        for defect in ('legacy-object','log-group-ocid','missing-values','duplicate','missing-entity'):
            with self.subTest(defect=defect):
                payload=deepcopy(self.payload)
                ui=payload['dashboards'][0]['saved-searches'][0]['ui-config']
                scope=ui['scopeFilters']
                if defect=='legacy-object':
                    ui['scopeFilters']={'isGlobal':False,'LogGroup':scope['filters'][0]}
                if defect=='log-group-ocid':scope['filters'][0]['values'][0]['value']='ocid1.loganalyticsloggroup.oc1.ap-sydney-1.TEST'
                if defect=='missing-values':scope['filters'][0].pop('values')
                if defect=='duplicate':scope['filters'].append(deepcopy(scope['filters'][0]))
                if defect=='missing-entity':scope['filters']=[f for f in scope['filters'] if f['type']!='Entity']
                with self.assertRaisesRegex(ValueError,'scope'):validate(payload)

    def test_terraform_placeholder_binding_and_api_conversion_preserve_scopes(self):
        config=dict(self.config,telemetry_compartment_id='__BH_TELEMETRY_COMPARTMENT_ID__',
                    dashboard_compartment_id='__BH_DASHBOARD_COMPARTMENT_ID__')
        api=api_payload(build(config))
        # Same three replacements as terraform/analytics.tf; no cloud calls.
        text=json.dumps(api).replace('__BH_TELEMETRY_COMPARTMENT_ID__','ocid1.compartment.oc1..TELEMETRY')
        text=text.replace('__BH_DASHBOARD_COMPARTMENT_ID__','ocid1.compartment.oc1..DASHBOARD')
        text=text.replace('__BH_ANALYTICS_LOG_GROUP_ID__','ocid1.loganalyticsloggroup.oc1.ap-sydney-1.GROUP')
        bound=json.loads(text)
        for search in bound['dashboards'][0]['savedSearches']:
            scope=search['uiConfig']['scopeFilters']
            filters={f['type']:f for f in scope['filters']}
            self.assertEqual(filters['LogGroup']['values'][0]['value'],'ocid1.compartment.oc1..TELEMETRY')
            self.assertEqual(filters['Entity']['flags']['ScopeCompartmentId'],'ocid1.compartment.oc1..TELEMETRY')
            self.assertIn("'Log Group' = 'ocid1.loganalyticsloggroup.oc1.ap-sydney-1.GROUP'",search['uiConfig']['queryString'])
            self.assertNotIn('__BH_',json.dumps(search))

    def test_counts_dedup_event_id_before_outcome_filter_and_keep_unknown_conflicts(self):
        for item in widgets(self.config)[:9]:
            self.assertLess(item['query'].index(' by EventID'),item['query'].index(" | where Outcome =") if item['key']=='unknown-status' else item['query'].rindex(' | where EventType'))
            self.assertIn('OutcomeVariants > 1',item['query'])
            self.assertIn('EventTime != null',item['query'])
            self.assertIn('toDate(EventTime) <= now()',item['query'])
        self.assertEqual([item['days'] for item in widgets(self.config)[:8]],[1]*4+[7]*4)

    def test_native_timestamp_is_normalized_before_valid_and_invalid_date_checks(self):
        # A real ingested native timestamp evaluates as 2026-11-11t02:54:21z.
        # ParseQuery accepts toDate(EventTime) but execution returns null.
        timestamp_field="'"+names(self.config['scope_id'])['label_prefix']+"EventTime'"
        for item in widgets(self.config):
            query=item['query']
            normalized='eval EventTime = upper('+timestamp_field+')'
            self.assertIn(normalized,query)
            self.assertLess(query.index(normalized),query.index('toDate(EventTime)'))
        invalid=next(item for item in widgets(self.config) if item['key']=='invalid-records')
        self.assertIn('toDate(EventTime) = null',invalid['query'])
        self.assertIn('toDate(EventTime) > now()',invalid['query'])

    def test_failure_history_preserves_events_not_latest_backup_state(self):
        definitions={item['key']:item for item in widgets(self.config)}
        history=definitions['failure-history']
        self.assertEqual(history['days'],30)
        self.assertIn("Outcome = literal(failure)",history['query'])
        self.assertNotIn('dedup BackupOCID',history['query'])
        self.assertIn('NOT ingestion health',definitions['last-observed']['title'])
        self.assertIn("Outcome = literal(unknown)",definitions['invalid-records']['query'])

    def test_aggregated_outcomes_use_explicit_literals_and_parser_safe_indicators(self):
        for item in widgets(self.config):
            query=item['query']
            self.assertIn('literal(success)',query)
            self.assertIn('literal(failure)',query)
            self.assertIn('literal(unknown)',query)
            for marker in ('🔴','🟢','⚪'):
                self.assertNotIn(marker,query)
                encoded=base64.b64encode(marker.encode()).decode()
                self.assertIn('decode64("'+encoded+'")',query)

    def test_daily_tables_aggregate_unique_events_before_counting_each_day(self):
        trends=[item for item in widgets(self.config) if item['key'].endswith('-trend')]
        self.assertEqual(len(trends),2)
        for item in trends:
            self.assertEqual(item['viz'],'summary_table')
            self.assertEqual(item['days'],30)
            query=item['query']
            self.assertNotIn('timestats',query)  # Oracle rejects timestats after stats.
            self.assertLess(query.index(' by EventID'),query.index('stats count as Events by Day, Outcome'))
            self.assertIn('dateSet(EventDate, hour, 0, minute, 0, sec, 0, msec, 0)',query)
            self.assertTrue(query.endswith('sort Day'))

    def test_native_shapes_and_real_sdk_api_models_match(self):
        for search in self.dashboard['saved-searches']:
            self.assertIn(search['ui-config']['visualizationType'],('tile','summary_table','records_histogram'))
        data=api_payload(self.payload)['dashboards'][0]
        self.assertTrue(set(data).issubset(set(oci.management_dashboard.models.ManagementDashboardForImportExportDetails().attribute_map.values())))
        for search in data['savedSearches']:
            self.assertIn('widgetVM',search)
            self.assertIn('queryString',search['uiConfig'])
            self.assertTrue(set(search).issubset(set(oci.management_dashboard.models.ManagementSavedSearchForImportDetails().attribute_map.values())))
        for tile in data['tiles']:
            self.assertTrue(set(tile).issubset(set(oci.management_dashboard.models.ManagementDashboardTileDetails().attribute_map.values())))

    def test_checked_in_dashboard_is_reproducible(self):
        config=dict(self.config, telemetry_compartment_id='__BH_TELEMETRY_COMPARTMENT_ID__',
                    dashboard_compartment_id='__BH_DASHBOARD_COMPARTMENT_ID__')
        expected=build(config)
        self.assertEqual(json.loads((ROOT/'dashboards/backup-health.management.json').read_text()),expected)
        self.assertEqual(json.loads((ROOT/'dashboards/backup-health.management.api.json').read_text()),api_payload(expected))

    def test_cli_and_api_dashboard_include_actual_png_preview(self):
        image=self.dashboard['screen-image']
        self.assertTrue(image.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(image.split(',',1)[1],validate=True),PREVIEW.read_bytes())
        self.assertEqual(api_payload(self.payload)['dashboards'][0]['screenImage'],image)
        self.assertNotIn('screen-image',api_payload(self.payload)['dashboards'][0])

    def test_missing_blank_placeholder_and_corrupt_previews_fail_before_deployment(self):
        for image in (None,'',' ','todo: provide value[mandatory]','data:image/png;base64,???',
                      'data:image/png;base64,'+base64.b64encode(b'not a PNG').decode(),
                      'data:image/png;base64,'+base64.b64encode(PREVIEW.read_bytes()[:-12]).decode()):
            with self.subTest(image=str(image)[:40]):
                payload=deepcopy(self.payload)
                if image is None:payload['dashboards'][0].pop('screen-image')
                else:payload['dashboards'][0]['screen-image']=image
                with self.assertRaisesRegex(ValueError,'screen-image'):validate(payload)
