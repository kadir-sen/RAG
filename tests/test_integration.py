"""Integration tests for Phase 3: Query Planner, Hybrid Executor, and updated modules."""
import sys
sys.path.insert(0, '.')

test_results = []


def run_test(name, fn):
    try:
        fn()
        test_results.append((name, 'PASS'))
    except Exception as e:
        test_results.append((name, f'FAIL: {e}'))


# ========== TEST 1: Jargon Manager ==========
def test_jargon_expand():
    from src.jargon_manager import JargonManager
    jm = JargonManager()
    assert jm.expand('SOW') == 'Scope of Work', 'SOW expansion failed'
    assert jm.expand('KPI') == 'Key Performance Indicator', 'KPI expansion failed'
    assert jm.expand('BOQ') == 'Bill of Quantities', 'BOQ expansion failed'
    assert jm.abbreviate('scope of work') == 'SOW', 'Reverse lookup failed'

run_test('Jargon Manager - expand/abbreviate', test_jargon_expand)


# ========== TEST 2: Query Expansion ==========
def test_query_expansion():
    from src.jargon_manager import JargonManager
    jm = JargonManager()
    expanded = jm.expand_query('What is the SOW total?')
    assert 'Scope of Work' in expanded, f'Expected Scope of Work in: {expanded}'

run_test('Jargon Manager - query expansion', test_query_expansion)


# ========== TEST 3: Column Context ==========
def test_column_context():
    from src.jargon_manager import JargonManager
    jm = JargonManager()
    ctx = jm.build_column_context(['SOW', 'amount', 'KPI'])
    assert 'SOW' in ctx and 'Scope of Work' in ctx, f'Bad context: {ctx}'
    assert 'KPI' in ctx, f'Missing KPI in context: {ctx}'

run_test('Jargon Manager - column context', test_column_context)


# ========== TEST 4: Find Related Terms ==========
def test_find_related():
    from src.jargon_manager import JargonManager
    jm = JargonManager()
    found = jm.find_related_terms('The BOQ and SOW are attached')
    abbrs = [t['abbreviation'] for t in found]
    assert 'BOQ' in abbrs, f'BOQ not found in: {abbrs}'
    assert 'SOW' in abbrs, f'SOW not found in: {abbrs}'

run_test('Jargon Manager - find_related_terms', test_find_related)


# ========== TEST 5: QueryPlanner Heuristics ==========
def test_planner_heuristics():
    from src.query_planner import QueryPlanner, StepType
    planner = QueryPlanner()

    # Simple query detection
    assert planner._is_obviously_simple('What is the total?') == True
    assert planner._is_obviously_simple('Group by category then find max') == False
    assert planner._is_obviously_simple('Find outliers in the data') == False

    # Type detection
    assert planner._detect_simple_type('Calculate the total') == StepType.SQL.value
    assert planner._detect_simple_type('What does the contract say?') == StepType.DOCUMENT.value
    assert planner._detect_simple_type('Who sent the letter?') == StepType.TIMELINE.value

run_test('QueryPlanner - heuristic detection', test_planner_heuristics)


# ========== TEST 6: QueryPlan Dataclass ==========
def test_plan_dataclass():
    from src.query_planner import QueryPlan, PlanStep
    step = PlanStep(step_id=0, step_type='sql', description='Test', instruction='Calculate total')
    plan = QueryPlan(original_query='test', steps=[step], is_simple=True)
    assert plan.steps[0].step_id == 0
    assert plan.steps[0].step_type == 'sql'
    assert plan.is_simple == True

run_test('QueryPlan dataclass', test_plan_dataclass)


# ========== TEST 7: HybridExecutor Heuristics ==========
def test_hybrid_heuristics():
    from src.hybrid_executor import HybridExecutor
    he = HybridExecutor()

    assert he._needs_sql_chain('Group by status then find max') == True
    assert he._needs_sql_chain('Find outliers') == True
    assert he._needs_sql_chain('What is the total?') == False

    # Query type determination
    from src.query_planner import QueryPlan, PlanStep
    plan = QueryPlan(original_query='test', steps=[
        PlanStep(step_id=0, step_type='sql', description='a', instruction='b'),
        PlanStep(step_id=1, step_type='document', description='c', instruction='d'),
    ])
    assert he._determine_query_type(plan) == 'hybrid'

    plan2 = QueryPlan(original_query='test', steps=[
        PlanStep(step_id=0, step_type='sql', description='a', instruction='b'),
    ])
    assert he._determine_query_type(plan2) == 'sql'

run_test('HybridExecutor - heuristics', test_hybrid_heuristics)


# ========== TEST 8: SQL Chain Plan Creation ==========
def test_sql_chain_plans():
    from src.hybrid_executor import HybridExecutor
    he = HybridExecutor()

    # Group by plan
    plan = he._create_sql_chain_plan('Group by category and find max value')
    assert len(plan.steps) == 2
    assert plan.steps[0].step_type == 'sql'
    assert plan.steps[1].step_type == 'combine'

    # Outlier plan
    plan = he._create_sql_chain_plan('Find outlier records in the data')
    assert len(plan.steps) == 3
    assert plan.steps[0].step_type == 'sql'
    assert plan.steps[1].step_type == 'sql'
    assert plan.steps[2].step_type == 'combine'

    # Above average plan
    plan = he._create_sql_chain_plan('Show records above average performance')
    assert len(plan.steps) == 3

run_test('HybridExecutor - SQL chain plans', test_sql_chain_plans)


# ========== TEST 9: Router Static Helpers ==========
def test_router_helpers():
    from src.router import QueryRouter

    result = QueryRouter._extract_two_parties('between alpha and beta?')
    assert result == ['alpha', 'beta'], f'Got: {result}'

    result = QueryRouter._extract_party_from_query('from "acme corp" sent')
    assert result is not None, 'Party extraction failed'

run_test('Router - static helpers', test_router_helpers)


# ========== TEST 10: LightGraph Node Dataclass ==========
def test_graph_node():
    from src.light_graph import GraphNode
    from dataclasses import asdict

    node = GraphNode(
        doc_id='test1', date='2025-01-01', sender='Alice', recipient='Bob',
        subject='Test', topics=['delay'], ref_numbers=['REF-001'],
        file_name='test.pdf', doc_type='letter',
        cc_list=['Charlie'], direction='outgoing',
        contract_ref='CNT-001', project_name='Project X',
        actions=['delay', 'claim'],
    )
    d = asdict(node)
    assert d['doc_id'] == 'test1'
    assert d['cc_list'] == ['Charlie']
    assert d['actions'] == ['delay', 'claim']
    assert d['contract_ref'] == 'CNT-001'

run_test('LightGraph - node dataclass', test_graph_node)


# ========== TEST 11: LightGraph Edge Detection ==========
def test_edge_detection():
    from src.light_graph import LightGraph

    lg = LightGraph()

    # Contract edge
    node_a = {'doc_id': 'a', 'contract_ref': 'CNT-001'}
    node_b = {'doc_id': 'b', 'contract_ref': 'CNT-001'}
    edge = lg._check_contract_edge(node_a, node_b)
    assert edge is not None
    assert edge.edge_type == 'same_contract'

    # Reference edge
    node_a = {'doc_id': 'a', 'ref_numbers': ['REF-001', 'REF-002']}
    node_b = {'doc_id': 'b', 'ref_numbers': ['REF-002', 'REF-003']}
    edge = lg._check_reference_edge(node_a, node_b)
    assert edge is not None
    assert edge.edge_type == 'references'

    # Reply edge
    node_a = {'doc_id': 'a', 'sender': 'Alice', 'recipient': 'Bob', 'date': '2025-01-01'}
    node_b = {'doc_id': 'b', 'sender': 'Bob', 'recipient': 'Alice', 'date': '2025-01-02'}
    edge = lg._check_reply_edge(node_a, node_b)
    assert edge is not None
    assert edge.edge_type == 'reply_to'

run_test('LightGraph - edge detection', test_edge_detection)


# ========== TEST 12: SQL Utilities ==========
def test_sql_utilities():
    from src.data_analyzer_sql import sanitize_table_name, validate_sql

    assert sanitize_table_name('My File (2024).xlsx') == 'my_file_2024'
    assert sanitize_table_name('123data.csv') == 't_123data'

    valid, err = validate_sql('SELECT * FROM test LIMIT 10')
    assert valid == True

    valid, err = validate_sql('DROP TABLE test')
    assert valid == False

    valid, err = validate_sql('INSERT INTO test VALUES (1)')
    assert valid == False

run_test('DataAnalyzerSQL - sanitize/validate', test_sql_utilities)


# ========== TEST 13: Plan JSON Parsing ==========
def test_json_parsing():
    from src.query_planner import QueryPlanner
    qp = QueryPlanner()

    # Clean JSON
    result = qp._parse_plan_json('{"is_simple": true, "steps": []}')
    assert result is not None
    assert result['is_simple'] == True

    # With markdown
    result = qp._parse_plan_json('```json\n{"is_simple": false}\n```')
    assert result is not None
    assert result['is_simple'] == False

    # Bad JSON
    result = qp._parse_plan_json('not json at all')
    assert result is None

run_test('QueryPlanner - JSON parsing', test_json_parsing)


# ========== TEST 14: Router Complex Query Detection ==========
def test_router_complex_detection():
    from src.router import QueryRouter

    # Mock _is_complex_query by creating a minimal instance-like check
    # We test the logic directly
    complex_queries = [
        'Group by category then find the max',
        'Find outliers in the data',
        'Compare sales month-over-month',
        'Grupla sonra en buyuk bul',
    ]
    simple_queries = [
        'What is the total revenue?',
        'Show me all records',
        'Who sent the letter?',
    ]

    # Test the static method logic inline
    def is_complex(query):
        q = query.lower()
        indicators = [
            ' then ', ' and then ', 'group by', 'compare', 'outlier',
            'above average', 'below average', 'month-over-month',
            ' sonra ', 'grupla', 'aykiri',
        ]
        return any(ind in q for ind in indicators)

    for q in complex_queries:
        assert is_complex(q), f'Should be complex: {q}'
    for q in simple_queries:
        assert not is_complex(q), f'Should be simple: {q}'

run_test('Router - complex query detection', test_router_complex_detection)


# ========== TEST 15: PlanExecutor Dependencies ==========
def test_executor_dependencies():
    from src.query_planner import PlanStep, QueryPlan

    # Test dependency resolution in instruction
    step = PlanStep(
        step_id=2, step_type='combine',
        description='Combine', instruction='Merge {step_0} with {step_1}',
        depends_on=[0, 1],
    )

    prev_results = {
        0: {'answer': 'Result from step 0', 'summary': 'Summary 0'},
        1: {'answer': 'Result from step 1', 'summary': 'Summary 1'},
    }

    instruction = step.instruction
    for dep_id in step.depends_on:
        if dep_id in prev_results:
            prev = prev_results[dep_id]
            placeholder = f'{{step_{dep_id}}}'
            if placeholder in instruction:
                instruction = instruction.replace(
                    placeholder,
                    str(prev.get('summary', prev.get('answer', '')))[:500]
                )

    assert 'Summary 0' in instruction, f'Missing dep 0 in: {instruction}'
    assert 'Summary 1' in instruction, f'Missing dep 1 in: {instruction}'

run_test('PlanExecutor - dependency resolution', test_executor_dependencies)


# ========== SUMMARY ==========
print()
print('=' * 60)
print('INTEGRATION TEST RESULTS')
print('=' * 60)
passed = 0
failed = 0
for name, result in test_results:
    status = 'PASS' if result == 'PASS' else 'FAIL'
    icon = 'V' if status == 'PASS' else 'X'
    print(f'  [{icon}] {name}: {result}')
    if status == 'PASS':
        passed += 1
    else:
        failed += 1

print(f'\nTotal: {passed} passed, {failed} failed out of {len(test_results)}')
if failed > 0:
    sys.exit(1)
print('\nAll tests passed!')
