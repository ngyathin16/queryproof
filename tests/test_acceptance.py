import copy
import unittest

from queryproof.engine import review
from queryproof.fixtures import CONTRACT, GOOD_SQL, commerce_bundle
from queryproof.importer import import_bundle
from queryproof.worker import execute


class AcceptanceBoundaries(unittest.TestCase):
    def test_relationship_paths_can_traverse_a_declared_dimension(self):
        bundle = commerce_bundle()
        bundle['manifest']['tables'].append({'name': 'regions', 'file': 'regions.csv', 'columns': [{'name': 'region', 'type': 'VARCHAR'}, {'name': 'country_id', 'type': 'INTEGER'}]})
        bundle['manifest']['tables'].append({'name': 'countries', 'file': 'countries.csv', 'columns': [{'name': 'country_id', 'type': 'INTEGER'}]})
        bundle['files'].update({'regions.csv': 'region,country_id\nHong Kong,1\nSingapore,2\n', 'countries.csv': 'country_id\n1\n2\n'})
        contract = copy.deepcopy(CONTRACT)
        contract['relationships'] = [
            {'table': 'regions', 'local_key': ['region'], 'remote_key': ['region'], 'cardinality': 'many-to-one'},
            {'source_table': 'regions', 'table': 'countries', 'local_key': ['country_id'], 'remote_key': ['country_id'], 'cardinality': 'many-to-one'}]
        sql = "SELECT o.region, SUM(o.revenue) AS revenue FROM orders o LEFT JOIN regions r ON o.region=r.region LEFT JOIN countries c ON r.country_id=c.country_id WHERE o.status='paid' AND o.ordered_at >= '2026-10-01' AND o.ordered_at < '2026-11-01' GROUP BY o.region"
        snapshot = import_bundle(bundle)
        self.assertEqual(review(snapshot, contract, sql)['status'], 'passed on this snapshot')
        bundle['files']['countries.csv'] += '1\n'
        self.assertEqual(review(import_bundle(bundle), contract, sql)['status'], 'needs definition')

    def test_import_rejects_double_overflow_and_invalid_empty_schema(self):
        for kind, text in [('DOUBLE', '1e999'), ('DECIMAL(39,2)', '')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                import_bundle({'manifest': {'tables': [{'name': 'sample', 'file': 'sample.csv', 'columns': [{'name': 'value', 'type': kind}]}]}, 'files': {'sample.csv': 'value\n' + (text + '\n' if text else '')}})

    def test_date_does_not_silently_discard_time(self):
        with self.assertRaisesRegex(ValueError, 'without a time component'):
            import_bundle({'manifest': {'tables': [{'name': 'sample', 'file': 'sample.csv', 'columns': [{'name': 'value', 'type': 'DATE'}]}]}, 'files': {'sample.csv': 'value\n2026-01-01 23:59:59\n'}})

    def test_ratio_denominator_is_checked_when_all_numerators_are_zero(self):
        bundle = commerce_bundle()
        for value in ('120.00', '80.00', '150.00', '50.00'):
            bundle['files']['orders.csv'] = bundle['files']['orders.csv'].replace(value, '0.00')
        snapshot = import_bundle(bundle)
        contract = copy.deepcopy(CONTRACT)
        contract['measure'] = {'aggregation': 'ratio', 'alias': 'revenue',
                               'numerator': {'column': 'revenue', 'aggregation': 'sum'},
                               'denominator': {'column': 'revenue', 'aggregation': 'count'}}
        correct = GOOD_SQL.replace('SUM(o.revenue)', 'SUM(o.revenue) / NULLIF(COUNT(o.revenue), 0)')
        wrong = correct.replace('COUNT(o.revenue)', 'COUNT(*)')
        self.assertEqual(review(snapshot, contract, correct)['status'], 'passed on this snapshot')
        result = review(snapshot, contract, wrong)
        self.assertEqual(result['status'], 'issue found')
        self.assertEqual(result['difference']['groups'], [])
        finding = next(c for c in result['checks'] if c['id'] == 'nulls')
        self.assertEqual(execute(snapshot, [finding['diagnostic_sql']])[0]['row_count'], finding['count'])


if __name__ == '__main__':
    unittest.main()
