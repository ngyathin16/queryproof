"""Freeze structural cases and independent row answers before detector execution."""
import copy
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path

from generate_cases import bundle

ROOT = Path(__file__).parent


def expected(rows, contract):
    selected = []
    for row in rows:
        if any(row[f['column']] not in f['value'] for f in contract['filters']):
            continue
        period = contract['time']
        if row[period['column']] is None or not period['start'] <= row[period['column']] < period['end']:
            continue
        selected.append(row)
    grouped = defaultdict(list)
    if not contract['groups']:
        grouped[()] = []
    for row in selected:
        grouped[tuple(row[c] for c in contract['groups'])].append(row)

    def aggregate(members, measure):
        values = [1 if measure['column'] == '*' else r[measure['column']] for r in members]
        if contract['null_policy'] == 'zero':
            values = [0 if v is None else v for v in values]
        values = [v for v in values if v is not None]
        if measure['aggregation'] == 'count':
            return Decimal(len(values))
        if measure['aggregation'] == 'count_distinct':
            return Decimal(len(set(values)))
        if not values:
            return None
        answer = sum(Decimal(str(v)) for v in values)
        return answer / len(values) if measure['aggregation'] == 'avg' else answer

    answers = []
    for keys, members in grouped.items():
        measure = contract['measure']
        if measure['aggregation'] == 'ratio':
            numerator, denominator = [aggregate(members, measure[part]) for part in ('numerator', 'denominator')]
            value = numerator / denominator if numerator is not None and denominator else None
        else:
            value = aggregate(members, measure)
        rounding = ROUND_HALF_EVEN if contract['rounding'] == 'half_even' else ROUND_HALF_UP
        if value is not None:
            value = str(value.quantize(Decimal(1).scaleb(-contract['decimal_scale']), rounding=rounding))
        answers.append({**dict(zip(contract['groups'], keys)), measure['alias']: value})
    return {'groups': answers, 'population': [[r[k] for k in contract['stable_key']] for r in selected]}


def fixture(kind):
    configurations = [
        ('ledger', ['entry'], 'DECIMAL(18,2)', 'sum', ['account'], 'preserve', 'one-to-many'),
        ('attributions', ['campaign', 'person'], 'DECIMAL(18,2)', 'sum', ['campaign'], 'preserve', 'many-to-many'),
        ('subscriptions', ['subscription'], 'DECIMAL(18,2)', 'ratio', [], 'preserve', 'one-to-many'),
        ('readings', ['device', 'sequence'], 'DOUBLE', 'avg', ['device', 'enabled'], 'zero', 'many-to-many'),
        ('inventory', ['warehouse', 'sku'], 'VARCHAR', 'count_distinct', ['warehouse'], 'preserve', 'many-to-many'),
        ('sessions', ['session'], 'DECIMAL(18,2)', 'avg', ['channel'], 'preserve', 'one-to-many'),
    ]
    table, keys, numeric, aggregation, groups, nulls, cardinality = configurations[kind]
    ids = list(dict.fromkeys(keys + groups))
    columns = [{'name': key, 'type': 'BOOLEAN' if key == 'enabled' else 'INTEGER' if key in keys else 'VARCHAR'} for key in ids]
    columns += [{'name': 'value', 'type': numeric}, {'name': 'exposure', 'type': 'DECIMAL(18,2)'},
                {'name': 'state', 'type': 'VARCHAR'}, {'name': 'occurred', 'type': 'DATE' if kind == 4 else 'TIMESTAMP'}]
    values = [['10', '-10', '30', None, '0', '90', '80', '70'],
              ['12', '8', '15', None, '0', '60', '70', '80'],
              ['0', '0', '0', None, '0', '60', '70', '80'],
              ['0.1', '0.2', '0.3', None, '0.0', '60', '70', '80'],
              ['red', 'red', 'blue', None, 'green', 'amber', 'black', 'white'],
              ['0', '0', '0', None, '0', '60', '70', '80']][kind]
    rows = []
    for index, value in enumerate(values):
        row = {}
        for key in ids:
            if key == 'enabled':
                row[key] = index % 2 == 0
            elif key in keys:
                row[key] = (index // 2 + 1) if len(keys) > 1 and key == keys[0] else index % 2 + 1 if len(keys) > 1 else index + 1
            else:
                row[key] = None if index == 3 else 'A'
        if kind == 4:
            date = ['2026-01-01', '2026-01-15', '2026-01-31', '2026-01-20', '2026-01-10', '2026-01-11', '2026-02-01', '2025-12-31'][index]
        else:
            date = ['2026-01-01 00:00:00', '2026-01-15 12:00:00', '2026-01-31 23:59:59', '2026-01-20 00:00:00', '2026-01-10 00:00:00', '2026-01-11 00:00:00', '2026-02-01 00:00:00', '2025-12-31 23:59:59'][index]
        row.update(value=value, exposure=None if index == 3 else str(index + 1), state='draft' if index == 5 else 'included', occurred=date)
        rows.append(row)
    remote = keys[:1] if cardinality == 'many-to-many' else keys
    child_columns = [c for c in columns if c['name'] in remote] + [{'name': 'tag', 'type': 'INTEGER'}]
    child_rows = [{**{key: row[key] for key in remote}, 'tag': tag} for row in rows for tag in (1, 2)]
    dimension_columns = [c for c in columns if c['name'] in remote] + [{'name': 'label', 'type': 'VARCHAR'}]
    dimension_rows = [dict(zip(remote, key), label='known') for key in sorted({tuple(r[k] for k in remote) for r in rows})]
    measure = {'column': 'value', 'aggregation': aggregation, 'alias': 'metric'}
    if aggregation == 'ratio':
        measure = {'aggregation': 'ratio', 'alias': 'metric', 'numerator': {'column': 'value', 'aggregation': 'sum'}, 'denominator': {'column': 'exposure', 'aggregation': 'count'}}
    contract = {'name': table + ' metric', 'base_table': table, 'grain': 'one ' + '/'.join(keys), 'stable_key': keys,
                'measure': measure, 'groups': groups, 'relationships': [
                    {'table': 'tags', 'local_key': remote, 'remote_key': remote, 'cardinality': cardinality},
                    {'table': 'dimensions', 'local_key': remote, 'remote_key': remote, 'cardinality': 'many-to-one'}],
                'filters': [{'column': 'state', 'op': 'in', 'value': ['included']}],
                'time': {'column': 'occurred', 'start': '2026-01-01', 'end': '2026-02-01', 'timezone': 'UTC'},
                'units': 'distinct labels' if kind == 4 else 'fixture units', 'null_policy': nulls, 'decimal_scale': 4,
                'rounding': 'half_up' if kind == 3 else 'half_even', 'absolute_tolerance': 0, 'relative_tolerance': 0}
    tables = {table: (columns, rows), 'tags': (child_columns, child_rows), 'dimensions': (dimension_columns, dimension_rows)}
    return tables, contract


def query(contract, *, join='', prefix='', extra='', population=True, end='<', expression=None):
    def aggregate(measure):
        col = 'b.' + measure['column']
        if contract['null_policy'] == 'zero':
            col = f'COALESCE({col}, 0)'
        if measure['aggregation'] == 'count_distinct':
            return f'COUNT(DISTINCT {col})'
        return measure['aggregation'].upper() + '(' + col + ')'
    metric = contract['measure']
    if expression is None:
        expression = (aggregate(metric['numerator']) + ' / NULLIF(' + aggregate(metric['denominator']) + ',0)') if metric['aggregation'] == 'ratio' else aggregate(metric)
    groups = ['b.' + group for group in contract['groups']]
    where = (["b.state IN ('included')"] if population else []) + ["b.occurred >= '2026-01-01'", f"b.occurred {end} '2026-02-01'"]
    if extra:
        where.append(extra)
    sql = prefix + 'SELECT ' + ', '.join(groups + [expression + ' AS metric']) + ' FROM ' + contract['base_table'] + ' b ' + join + ' WHERE ' + ' AND '.join(where)
    return sql + (' GROUP BY ' + ', '.join(groups) if groups else '')


def build():
    cases = []
    for kind in range(6):
        tables, contract = fixture(kind)
        source = bundle(tables, contract['base_table'] + ' structural fixture')
        base_rows = tables[contract['base_table']][1]
        reference = expected(base_rows, contract)
        remote = contract['relationships'][0]['remote_key']
        on = ' AND '.join(f'b.{k} = t.{k}' for k in remote)
        dimension_on = ' AND '.join(f'b.{k} = d.{k}' for k in remote)
        keys = ', '.join(remote)
        preaggregate = f'WITH tag_groups AS (SELECT {keys}, COUNT(*) AS n FROM tags GROUP BY {keys}) '
        good = query(contract, prefix=preaggregate, join='LEFT JOIN tag_groups t ON ' + on + ' LEFT JOIN dimensions d ON ' + dimension_on)

        def add(family, name, sql, status, modified=None):
            cases.append({'id': f'v2-{contract["base_table"]}-{name}', 'split': 'evaluation', 'family': family,
                          'name': name, 'bundle': source, 'contract': modified or copy.deepcopy(contract),
                          'sql': sql, 'expected_status': status, 'expected': reference,
                          'repairable': family in ('join', 'population', 'date', 'null'), 'known_solution': good})

        add('join', 'repeated-branch', query(contract, join='LEFT JOIN tags t ON ' + on), 'issue found')
        add('population', 'missing-zero-entity', query(contract, extra=f'b.{contract["stable_key"][-1]} != {base_rows[4][contract["stable_key"][-1]]}') if kind in (0, 2, 5) else query(contract, population=False), 'issue found')
        add('date', 'inclusive-end', query(contract, end='<='), 'issue found')
        # Zero numerators keep results identical despite a wrong ratio/AVG denominator.
        bad_null = query(contract, expression='SUM(b.value) / COUNT(*)') if kind in (2, 5) else query(contract, extra='b.value IS NOT NULL')
        add('null', 'unknown-denominator' if kind in (2, 5) else 'unknown-row-loss', bad_null, 'issue found')
        add('valid', 'preaggregate-and-dimension', good, 'passed on this snapshot')
        if kind == 0:
            alternative = query(contract, expression='SUM(CAST(b.value AS DECIMAL(18,2))) + 0.00004')
        elif kind == 3:
            alternative = query(contract, expression='AVG(COALESCE(b.value,0)) + 0.000049')
        else:
            alternative = query(contract, join='INNER JOIN dimensions d ON ' + dimension_on)
        add('valid', 'rounding-or-many-to-one', alternative, 'passed on this snapshot')
        for field in (('grain', 'time'), ('stable_key', 'relationships'), ('measure', 'null_policy'), ('units', 'rounding'), ('filters', 'decimal_scale'), ('groups', 'absolute_tolerance'))[kind]:
            incomplete = copy.deepcopy(contract)
            del incomplete[field]
            add('definition', 'missing-' + field, good, 'needs definition', incomplete)
        for index, bad in enumerate([good + ' LIMIT 1', good.replace('SELECT ', 'SELECT DISTINCT ', 1)]):
            add('unsupported', 'grammar-' + str(index), bad, 'unsupported')
    assert len(cases) == 60
    return cases


def main():
    destination = ROOT / 'v2'
    destination.mkdir(exist_ok=True)
    if (destination / 'cases.json').exists():
        raise SystemExit('Frozen v2 already exists; create another version.')
    old = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))
    content = {'version': 2, 'development': old['development'], 'evaluation': build()}
    raw = (json.dumps(content, indent=2) + '\n').encode()
    (destination / 'cases.json').write_bytes(raw)
    manifest = {'version': 2, 'sha256': hashlib.sha256(raw).hexdigest(), 'frozen_before_execution': True,
                'counts': {'development': 60, 'evaluation': 60},
                'per_split': {'join': 6, 'population': 6, 'date': 6, 'null': 6, 'valid': 12, 'definition': 12, 'unsupported': 12},
                'development': 'Previously frozen v1 development, unchanged; already inspected regression cases.',
                'evaluation': 'Six schemas: signed ledger, compound attribution bridge, nonadditive ratio, compound device readings, distinct inventory labels, zero-valued session averages. Compound many-to-many relationship keys, separate dimension joins, preaggregated branches and distinct projection/filter shapes differ from development.',
                'oracle': 'Standalone Python row calculation in generate_v2.py, no queryproof/DuckDB/SQLGlot import.',
                'provenance': 'Agent-authored fictional records. No customer data or human review.',
                'claims': 'First execution retained. After inspection this is regression evidence, not continuing unseen accuracy.'}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
