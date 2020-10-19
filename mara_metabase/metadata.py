import sys
import time

import mara_schema.config
from mara_schema.metric import Metric, SimpleMetric, ComposedMetric, Aggregation

from . import config
from .client import MetabaseClient


def update_metadata() -> bool:
    """Updates descriptions of tables & fields in Metabase, creates metrics and flushes field caches"""
    client = MetabaseClient()

    dwh_db_id = next(filter(lambda db: db['name'] == config.metabase_data_db_name(),
                            client.get('/api/database/')),
                     {}).get('id')

    if not dwh_db_id:
        print(f'Database {config.metabase_data_db_name()} not found in Metabase', file=sys.stderr)
        return False

    print('.. Triggering schema sync')
    client.post(f'/api/database/{dwh_db_id}/sync_schema')

    seconds = config.seconds_to_wait_for_schema_sync()
    print(f'.. Waiting {seconds} seconds')
    time.sleep(seconds)

    metadata = client.get(f'/api/database/{dwh_db_id}/metadata?include_hidden=true')
    data_sets = {data_set.name: data_set for data_set in mara_schema.config.data_sets()}

    for table in metadata['tables']:
        data_set = data_sets.get(table['name'])
        if data_set:
            client.put(f'/api/table/{table["id"]}',
                       {'description': data_set.entity.description,
                        'show_in_getting_started': True,
                        'field_order': 'database'})

            _attributes = {}
            for path, attributes in data_set.connected_attributes().items():
                for name, attribute in attributes.items():
                    _attributes[name] = attribute

            for field in table['fields']:
                attribute = _attributes.get(field['name'], None)
                if attribute:
                    # https://github.com/metabase/metabase/blob/master/frontend/src/metabase/meta/types/Field.js
                    client.put(f'/api/field/{field["id"]}',
                               {'description': attribute.description or 'tbd',
                                'visibility_type': 'normal',
                                })
                else:
                    client.put(f'/api/field/{field["id"]}',
                               {'description': '>> technical field hidden by schema sync',
                                'visibility_type': 'sensitive'})

            for name, _metric in data_set.metrics.items():
                metric = {'name': name,
                          'description': _metric.description,
                          'table_id': table['id'],
                          'definition': {'source-table': table['id'],
                                         'aggregation': [
                                             metric_definition(_metric, table)
                                             if isinstance(_metric, SimpleMetric)
                                             else ['aggregation-options',
                                                   metric_definition(_metric, table),
                                                   {'display-name': _metric.display_formula()}
                                                   ]
                                         ]},
                          'show_in_getting_started': False,
                          'how_is_this_calculated': _metric.display_formula(),
                          'revision_message': 'Auto schema import'}

                existing_metric = next(filter(lambda m: m['name'] == name, table['metrics']), None)
                if existing_metric:
                    client.put(f'/api/metric/{existing_metric["id"]}', metric)
                else:
                    client.post('/api/metric', metric)

            for metric in table['metrics']:
                if metric['name'] not in data_set.metrics:
                    client.put(f'/api/metric/{metric["id"]}',
                               {'archived': True, 'revision_message': 'Auto schema import'})

        else:
            client.put(f'/api/table/{table["id"]}',
                       {'visibility_type': 'hidden'})

    print('.. Discarding field values')
    client.post(f'/api/database/{dwh_db_id}/discard_values')

    print('.. Rescanning field values')
    client.post(f'/api/database/{dwh_db_id}/rescan_values')

    return True


def metric_definition(metric: Metric, table) -> []:
    """Turn a Mara Schema metric into a a formula that Metabase understands"""

    from sympy.parsing import sympy_parser
    from sympy.core.expr import Expr

    if isinstance(metric, SimpleMetric):
        field = next(filter(lambda f: f['name'] == metric.name, table['fields']), None)
        if not field:
            print(f"No field found for measure {metric.name} in table {table['name']}", file=sys.stderr)
            return 1
        else:
            # https://github.com/metabase/metabase/blob/master/backend/mbql/src/metabase/mbql/schema.clj#L299
            aggregation = metric.aggregation if metric.aggregation != Aggregation.DISTINCT_COUNT else 'distinct'
            return [aggregation, ['field-id', field['id']]]

    elif isinstance(metric, ComposedMetric):
        # assign variable names m0, m1, ... for all parent metrics
        parent_metrics = {f'm{i}': metric for i, metric in enumerate(metric.parent_metrics)}

        # render metric formula with m0, m1 as variables
        formula = metric.formula_template.format(*parent_metrics.keys())

        # parse expression with minimal transformations
        expression = sympy_parser.parse_expr(formula,
                                             transformations=[sympy_parser.auto_symbol, sympy_parser.auto_number],
                                             evaluate=False)
        assert (isinstance(expression, Expr))  # make sure it's an algebraic expression

        def s_expression(x):
            """Helper function for turning a sympy expression into something Metabase understands"""
            if isinstance(x, Expr):
                if x.is_Add:
                    return ['+', *map(s_expression, x.args)]
                if x.is_Mul:
                    return ['*', *map(s_expression, x.args)]
                if x.is_Pow and x.exp == -1:  # for some reason a / b is turned into a * b**-1
                    return ['/', 1, s_expression(x.base)]
                if x.is_Float:
                    return float(x)
                if x.is_Integer:
                    return int(x)
                if x.is_symbol:
                    if x.name not in parent_metrics:
                        raise NotImplementedError(f'Unknown symbol {x.name}')
                    return metric_definition(parent_metrics[x.name], table)
                else:
                    raise NotImplementedError(f'Formula generation not implemented for {type(x)}')

        return s_expression(expression)

    else:
        assert False
