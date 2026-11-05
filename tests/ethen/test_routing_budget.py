"""Independent adversarial contracts for durable coding-task budget reservations."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import subprocess
import sys
import threading

import pytest

from ethen.code.routing import BudgetLedger, Lane


def lane():
    return Lane('approved-test', 'fixture-model', Decimal(2), Decimal(4), approved=True)


def reserve(ledger, request='request', task='task', day='2026-11-05', **overrides):
    args = dict(tokens=100, task_tokens=1000, task_cost=Decimal(1), daily_cost=Decimal(1))
    args.update(overrides)
    return ledger.reserve(request, task, day, lane(), **args)


@pytest.mark.parametrize('price', [None, Decimal(-1), Decimal('NaN'), Decimal('Infinity')])
def test_unknown_or_invalid_pricing_denies_before_dispatch(tmp_path, price):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    unsafe = Lane('unpriced', 'fixture-model', price, Decimal(0), approved=True)
    with pytest.raises(PermissionError):
        ledger.reserve('r', 't', '2026-11-05', unsafe, 1, 1, Decimal(1), Decimal(1))
    # A denied attempt must not burn the request identifier.
    assert reserve(ledger, 'r')['reserved_tokens'] == 100


def test_known_price_still_requires_explicit_authorization(tmp_path):
    unapproved = Lane('api', 'fixture-model', Decimal(0), Decimal(0))
    with pytest.raises(PermissionError):
        BudgetLedger(tmp_path / 'budget.db').reserve('r', 't', '2026-11-05', unapproved, 1, 1, Decimal(0), Decimal(0))


def test_worst_case_input_output_price_is_reserved():
    assert lane().ceiling(100) == Decimal('0.0004')


@pytest.mark.parametrize('outcome', ['completed', 'cancelled', 'timeout', 'rate_limited', 'failed'])
def test_terminal_outcome_and_restart_never_refund_or_redispatch(tmp_path, outcome):
    path = tmp_path / 'budget.db'
    reserve(BudgetLedger(path), task_tokens=100)
    BudgetLedger(path).finish('request', outcome)
    with pytest.raises(PermissionError):
        reserve(BudgetLedger(path), task_tokens=100)
    with pytest.raises(PermissionError):
        reserve(BudgetLedger(path), request='retry', task_tokens=100)
    with pytest.raises(PermissionError):
        BudgetLedger(path).finish('request', 'completed')


def test_crashed_reserved_request_remains_fenced_after_restart(tmp_path):
    path = tmp_path / 'budget.db'
    reserve(BudgetLedger(path), task_cost=Decimal('0.0004'))
    with pytest.raises(PermissionError):
        reserve(BudgetLedger(path))
    with pytest.raises(PermissionError):
        reserve(BudgetLedger(path), request='new-id', task_cost=Decimal('0.0004'))


def test_task_tokens_are_cumulative_across_accounting_days(tmp_path):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger, task_tokens=100)
    with pytest.raises(PermissionError):
        reserve(ledger, request='next-day', day='2026-11-06', task_tokens=100)


def test_daily_limit_aggregates_distinct_tasks_and_does_not_block_next_day(tmp_path):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger, daily_cost=Decimal('0.0004'))
    with pytest.raises(PermissionError):
        reserve(ledger, request='other', task='other', daily_cost=Decimal('0.0004'))
    assert reserve(ledger, request='tomorrow', task='other', day='2026-11-06', daily_cost=Decimal('0.0004'))


def test_parallel_distinct_requests_cannot_oversubscribe_task(tmp_path):
    path = tmp_path / 'budget.db'
    BudgetLedger(path)
    barrier = threading.Barrier(2)

    def attempt(request):
        barrier.wait(timeout=10)
        try:
            reserve(BudgetLedger(path), request=request, task_tokens=100)
            return 'reserved'
        except PermissionError:
            return 'denied'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ['a', 'b'])) == ['denied', 'reserved']


def test_duplicate_effect_fence_crosses_process_boundary(tmp_path):
    path = tmp_path / 'budget.db'
    reserve(BudgetLedger(path))
    code = '''from decimal import Decimal
from pathlib import Path
import sys
from ethen.code.routing import BudgetLedger, Lane
try:
 BudgetLedger(Path(sys.argv[1])).reserve('request','task','2026-11-05',Lane('approved-test','fixture-model',Decimal(2),Decimal(4),approved=True),100,1000,Decimal(1),Decimal(1))
except PermissionError:
 print('DENIED')
else:
 raise SystemExit('duplicate redispatched')
'''
    result = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'DENIED'


@pytest.mark.parametrize('invalid', [True, 100.0, float('nan')])
def test_noninteger_task_token_ceiling_cannot_bypass_limit(tmp_path, invalid):
    with pytest.raises((ValueError, TypeError, PermissionError)):
        reserve(BudgetLedger(tmp_path / 'budget.db'), task_tokens=invalid)


def test_atomic_completion_receipt_survives_restart_without_redispatch(tmp_path):
    path = tmp_path / 'budget.db'
    ledger = BudgetLedger(path)
    reserve(ledger)
    receipt = {'issue': 'task', 'changed_files': ['calc.py'], 'test_exit_codes': [1, 0]}
    ledger.complete('request', receipt)
    recovered = BudgetLedger(path)
    assert recovered.receipt('request') == receipt
    with pytest.raises(PermissionError):
        reserve(recovered)
    with pytest.raises(PermissionError):
        recovered.complete('request', {'forged': True})
    assert recovered.receipt('request') == receipt


def test_invalid_receipt_does_not_complete_the_reservation(tmp_path):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger)
    with pytest.raises(ValueError):
        ledger.complete('request', {'cost': float('nan')})
    assert ledger.receipt('request') is None
    ledger.complete('request', {'cost': '0'})
    assert ledger.receipt('request') == {'cost': '0'}


def test_database_fault_rolls_back_both_completion_and_receipt(tmp_path):
    import sqlite3

    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger)
    with ledger.connect() as db:
        db.execute("CREATE TRIGGER fail_completion BEFORE UPDATE ON reservations WHEN NEW.state='completed' BEGIN SELECT RAISE(ABORT, 'owned fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.complete('request', {'result': 'must not be visible'})
    assert ledger.receipt('request') is None
    with ledger.connect() as db:
        db.execute('DROP TRIGGER fail_completion')
    ledger.complete('request', {'result': 'committed atomically'})
    assert ledger.receipt('request') == {'result': 'committed atomically'}


def test_cancelled_reservation_cannot_gain_completed_receipt(tmp_path):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger)
    ledger.finish('request', 'cancelled')
    with pytest.raises(PermissionError):
        ledger.complete('request', {'result': 'stale completion'})
    assert ledger.receipt('request') is None
