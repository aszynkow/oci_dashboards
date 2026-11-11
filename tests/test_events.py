from copy import deepcopy
import json
from pathlib import Path
import unittest
from oci_dashboards.deploy import example_event
from oci_dashboards.events import CREATE, COPY, GROUP_CREATE, GROUP_COPY, normalize, summarize

NOW = '2026-11-10T12:00:00Z'


class NativeEventTests(unittest.TestCase):
    def test_status_locations_are_supported_and_missing_or_conflicting_is_unknown(self):
        for location in ('root', 'data', 'details', 'missing', 'conflict'):
            event = example_event()
            event['data']['additionalDetails'].pop('status')
            if location == 'root': event['status'] = 'operationFailed'
            if location == 'data': event['data']['status'] = 'operationFailed'
            if location == 'details': event['data']['additionalDetails']['status'] = 'operationFailed'
            if location == 'conflict':
                event['status'] = 'operationFailed'
                event['data']['status'] = 'operationSucceed'
            with self.subTest(location=location):
                self.assertEqual(normalize(event, NOW)['outcome'], 'failure' if location in ('root','data','details') else 'unknown')

    def test_end_event_alone_does_not_imply_success(self):
        event = example_event()
        event['data']['additionalDetails']['status'] = 'newStatus'
        self.assertEqual(normalize(event, NOW)['outcome'], 'unknown')

    def test_duplicate_delivery_deduplicates_and_later_success_does_not_erase_failure(self):
        failed = example_event()
        failed['eventID'] = 'failure'
        failed['data']['additionalDetails']['status'] = 'operationFailed'
        success = example_event()
        success['eventID'] = 'success'
        copy = deepcopy(success)
        copy.update(eventID='copy', eventType=COPY)
        report = summarize([failed, deepcopy(failed), success, copy], NOW)
        self.assertEqual(report['recorded_outcomes'], {'failure':1, 'success':2, 'unknown':0})
        self.assertEqual(report['coverage'], 'unknown')
        self.assertEqual(report['ingestion_health'], 'unverified')

    def test_missing_identity_invalid_future_naive_time_and_begin_events_are_not_counted_healthy(self):
        for key, value in [('eventID', None), ('eventTime', 'bad'), ('eventTime', '2026-11-11T00:00:00Z'),
                           ('eventTime', '2026-11-10T00:00:00'), ('eventType', 'com.oraclecloud.blockvolumes.createvolumebackup.begin')]:
            event = example_event()
            event[key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(summarize([event], NOW)['recorded_outcomes']['success'],0)
                self.assertEqual(summarize([event], NOW)['invalid_records'],1)

    def test_conflicting_duplicate_identity_is_unknown_and_history_window_is_explicit(self):
        first = example_event()
        second = deepcopy(first)
        second['data']['additionalDetails']['status'] = 'operationFailed'
        self.assertEqual(summarize([first,second],NOW)['recorded_outcomes'], {'success':0,'failure':0,'unknown':1})
        first['eventTime'] = '2026-11-08T00:00:00Z'
        self.assertEqual(summarize([first],NOW,24)['recorded_outcomes']['success'],0)
        self.assertEqual(summarize([first],NOW,168)['recorded_outcomes']['success'],1)

    def test_empty_event_stream_never_means_healthy(self):
        report = summarize([],NOW)
        self.assertEqual(report['coverage'],'unknown')
        self.assertEqual(report['ingestion_health'],'unverified')


class GroupEventTests(unittest.TestCase):
    def setUp(self):
        self.events = json.loads((Path(__file__).parent/'fixtures/group-completion-events.json').read_text())['events']

    def test_real_group_shapes_have_correct_kind_operation_and_lineage(self):
        by_type = {e['eventType']: normalize(e, NOW) for e in self.events}
        creation = by_type[GROUP_CREATE]
        copied = by_type[GROUP_COPY]
        self.assertEqual((creation['resource_type'], creation['operation'], creation['outcome']), ('Volume group', 'create', 'success'))
        self.assertEqual(creation['group_id'], 'ocid1.volumegroup.oc1.ap-sydney-1.SAMPLE_GROUP')
        self.assertEqual((copied['resource_type'], copied['operation'], copied['outcome']), ('Volume group', 'copy', 'success'))
        self.assertEqual(copied['source_group_backup_id'], creation['resource_id'])
        self.assertEqual(copied['destination_region'], 'ap-melbourne-1')
        self.assertTrue(copied['resource_id'].startswith('ocid1.volumegroupbackup.oc1.ap-melbourne-1.'))
        self.assertEqual(copied['backup_type'], 'FULL')
        self.assertIsNone(copied['group_id'])  # Never invent unavailable group identity.
        member = by_type[COPY]
        self.assertEqual(member['resource_type'], 'Volume')  # Not necessarily a direct copy.
        self.assertEqual(member['source_volume_backup_id'], member['resource_id'])

    def test_completion_counts_keep_group_and_member_events_distinct_and_deduplicate_delivery(self):
        report = summarize(self.events + deepcopy(self.events), NOW)
        self.assertEqual(report['recorded_outcomes'], {'success': 4, 'failure': 0, 'unknown': 0})
        # One group backup + two member copies + one group copy. Requests/begins are excluded.
        self.assertEqual(report['invalid_records'], 4)
        self.assertEqual(report['coverage'], 'unknown')

    def test_group_missing_conflicting_failed_and_future_status_contract(self):
        source = next(e for e in self.events if e['eventType'] == GROUP_COPY)
        for variant in ('missing','conflicting','failed','future'):
            e = deepcopy(source)
            if variant == 'missing':e['data']['additionalDetails'].pop('status')
            if variant == 'conflicting':e['status'] = 'operationFailed'
            if variant == 'failed':e['data']['additionalDetails']['status'] = 'operationFailed'
            if variant == 'future':e['eventTime'] = '2026-11-11T10:00:00Z'
            with self.subTest(variant=variant):
                self.assertEqual(normalize(e, NOW)['outcome'], 'failure' if variant == 'failed' else 'unknown')

    def test_later_group_success_does_not_erase_a_failed_event(self):
        success = next(e for e in self.events if e['eventType'] == GROUP_COPY)
        failed = deepcopy(success)
        failed['eventID'] = 'SYNTHETIC-FAILED-ATTEMPT'
        failed['data']['additionalDetails']['status'] = 'operationFailed'
        self.assertEqual(summarize([failed, success], NOW)['recorded_outcomes'], {'success':1,'failure':1,'unknown':0})

    def test_group_request_or_begin_is_not_success_even_with_a_success_status(self):
        e = deepcopy(self.events[0])
        for kind in ('com.oraclecloud.blockvolumes.createvolumegroupbackup.begin', 'com.oraclecloud.blockvolumes.copyvolumegroupbackup'):
            e['eventType'] = kind
            e['data']['additionalDetails']['status'] = 'operationSucceed'
            with self.subTest(kind=kind):self.assertFalse(normalize(e, NOW)['valid'])
