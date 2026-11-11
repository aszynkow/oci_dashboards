from copy import deepcopy
import unittest
from oci_dashboards.deploy import example_event
from oci_dashboards.events import COPY, normalize, summarize

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
