"""Exact-boundary contracts for every ceiling the EV6-045 spend gate enforces.

Gap closed (independent review of b3edfe49f1, mutant Y03): the token ceiling was only tested at
"exactly equal allowed" and "far over denied", so a one-too-lenient comparison survived every non-E2E
test. Here each limit is probed at exactly the ceiling (allowed) and ceiling + 1 smallest unit (denied),
alone and cumulatively, for: task tokens, task cost, daily cost, the per-request output-token ceiling
and the provider attempt (session) cap. The accounting day comes from a frozen clock, never the real one.

Synthetic only: throwaway SQLite ledgers in tmp_path, no network, no model, no credentials.
"""
import json
import sqlite3
from datetime import datetime as real_datetime
from decimal import Decimal

import pytest

from ethen.code import provider_execution
from ethen.code.provider_execution import BoundedProvider, RouteStopped, token_ceiling
from ethen.code.routing import BudgetLedger, Lane

DAY = '2026-11-09'
OTHER_DAY = '2026-11-10'
# 1000 per million for input and output: one token costs exactly 0.001, so every cost boundary is an
# exact Decimal and the smallest representable overshoot is one token.
PRICED = Lane('boundary-lane', 'fixture-boundary', Decimal(1000), Decimal(1000), approved=True)
ZERO = Lane('boundary-zero', 'fixture-boundary', Decimal(0), Decimal(0), approved=True, synthetic=True)
BIG = Decimal(10 ** 9)
STATES = ['reserved', 'completed', 'failed', 'timeout', 'cancelled', 'rate_limited']


class FrozenClock:
    """Stands in for the module-level `datetime` name the provider stamps accounting days with."""

    def __init__(self, iso):
        self.set(iso)

    def set(self, iso):
        self.instant = real_datetime.fromisoformat(iso)

    def now(self, tz=None):
        return self.instant if tz is None else self.instant.astimezone(tz)


def reserve(ledger, request, *, task='task', day=DAY, lane=PRICED, tokens=100, task_tokens=BIG,
            task_cost=BIG, daily_cost=BIG):
    return ledger.reserve(request, task, day, lane, tokens, int(task_tokens), task_cost, daily_cost)


def settle(ledger, request, state):
    if state != 'reserved':
        ledger.finish(request, state)


# (reservations already made, new reservation, expected allowed) against a ceiling of 300 units
CASES = [((), 300, True), ((), 301, False), ((100,), 200, True), ((100,), 201, False),
         ((100, 100), 100, True), ((100, 100), 101, False), ((300,), 1, False)]


def exercise(tmp_path, prior, new, allowed, ceiling, **limits):
    """Apply prior reservations, then one more; denial must not consume the exact remaining headroom."""
    ledger = BudgetLedger(tmp_path / 'budget.db')
    for index, tokens in enumerate(prior):
        reserve(ledger, 'prior-%d' % index, tokens=tokens, **limits)
    if allowed:
        assert reserve(ledger, 'new', tokens=new, **limits)['reserved_tokens'] == new
        return
    with pytest.raises(PermissionError, match='ceiling exhausted'):
        reserve(ledger, 'new', tokens=new, **limits)
    remaining = ceiling - sum(prior)
    if remaining > 0:  # a denied attempt charges nothing and burns no request id
        assert reserve(ledger, 'new', tokens=remaining, **limits)['reserved_tokens'] == remaining


@pytest.mark.parametrize('prior,new,allowed', CASES)
def test_task_token_ceiling_is_exact_alone_and_cumulatively(tmp_path, prior, new, allowed):
    exercise(tmp_path, prior, new, allowed, 300, task_tokens=300)


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('prior,new,allowed', CASES)
def test_task_token_ceiling_counts_prior_reservations_in_every_state(tmp_path, prior, new, allowed, state):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    for index, tokens in enumerate(prior):
        reserve(ledger, 'prior-%d' % index, tokens=tokens, task_tokens=300)
        settle(ledger, 'prior-%d' % index, state)
    if allowed:
        assert reserve(ledger, 'new', tokens=new, task_tokens=300)
    else:
        with pytest.raises(PermissionError, match='ceiling exhausted'):
            reserve(ledger, 'new', tokens=new, task_tokens=300)


@pytest.mark.parametrize('prior,new,allowed', CASES)
def test_task_cost_ceiling_is_exact_alone_and_cumulatively(tmp_path, prior, new, allowed):
    exercise(tmp_path, prior, new, allowed, 300, task_cost=Decimal('0.300'))


@pytest.mark.parametrize('prior,new,allowed', CASES)
def test_daily_cost_ceiling_is_exact_alone_and_across_distinct_tasks(tmp_path, prior, new, allowed):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    for index, tokens in enumerate(prior):  # every prior reservation belongs to a different task
        reserve(ledger, 'prior-%d' % index, task='task-%d' % index, tokens=tokens, daily_cost=Decimal('0.300'))
    if allowed:
        assert reserve(ledger, 'new', task='task-new', tokens=new, daily_cost=Decimal('0.300'))
    else:
        with pytest.raises(PermissionError, match='ceiling exhausted'):
            reserve(ledger, 'new', task='task-new', tokens=new, daily_cost=Decimal('0.300'))


@pytest.mark.parametrize('field', ['task_cost', 'daily_cost'])
def test_cost_ceilings_have_no_tolerance_below_one_token(tmp_path, field):
    just_under = Decimal('0.300') - Decimal('1E-12')
    with pytest.raises(PermissionError, match='ceiling exhausted'):
        reserve(BudgetLedger(tmp_path / 'under.db'), 'r', tokens=300, **{field: just_under})
    assert reserve(BudgetLedger(tmp_path / 'exact.db'), 'r', tokens=300, **{field: Decimal('0.300')})


def test_daily_ceiling_counts_only_the_same_accounting_day(tmp_path):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger, 'yesterday', task='a', day=DAY, tokens=300, daily_cost=Decimal('0.300'))
    # the other day starts from zero: a full 300 is allowed once, the 301st token of that day is not
    assert reserve(ledger, 'today', task='b', day=OTHER_DAY, tokens=300, daily_cost=Decimal('0.300'))
    with pytest.raises(PermissionError, match='ceiling exhausted'):
        reserve(ledger, 'today-more', task='c', day=OTHER_DAY, tokens=1, daily_cost=Decimal('0.300'))
    with pytest.raises(PermissionError, match='ceiling exhausted'):
        reserve(ledger, 'again', task='d', day=DAY, tokens=1, daily_cost=Decimal('0.300'))


def test_task_ceilings_are_per_task_not_global(tmp_path):
    ledger = BudgetLedger(tmp_path / 'budget.db')
    reserve(ledger, 'a', task='task-a', tokens=300, task_tokens=300, task_cost=Decimal('0.300'))
    with pytest.raises(PermissionError, match='ceiling exhausted'):
        reserve(ledger, 'a2', task='task-a', tokens=1, task_tokens=300, task_cost=Decimal('0.300'))
    assert reserve(ledger, 'b', task='task-b', tokens=300, task_tokens=300, task_cost=Decimal('0.300'))


@pytest.mark.parametrize('bad', [0, -1, True, 1.5, '300', None])
def test_task_token_ceiling_must_be_a_positive_real_int(tmp_path, bad):
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / 'budget.db').reserve('r', 't', DAY, PRICED, 1, bad, BIG, BIG)


@pytest.mark.parametrize('bad', [0, -1, True, 1.5])
def test_reserved_token_count_must_be_a_positive_real_int(tmp_path, bad):
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / 'budget.db').reserve('r', 't', DAY, PRICED, bad, 1000, BIG, BIG)


@pytest.mark.parametrize('ceilings', [(Decimal(-1), BIG), (BIG, Decimal(-1)),
                                       (Decimal('NaN'), BIG), (BIG, Decimal('Infinity'))])
def test_cost_ceilings_must_be_finite_and_nonnegative(tmp_path, ceilings):
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / 'budget.db').reserve('r', 't', DAY, PRICED, 1, 1000, *ceilings)


def test_reserved_cost_is_tokens_times_the_higher_price_by_independent_arithmetic(tmp_path):
    lane = Lane('asym', 'fixture-boundary', Decimal(1000), Decimal(3000), approved=True)
    assert lane.ceiling(100) == Decimal('0.3')  # 100 * 3000 / 1e6, never 100 * 1000 / 1e6
    swapped = Lane('asym', 'fixture-boundary', Decimal(3000), Decimal(1000), approved=True)
    assert swapped.ceiling(100) == Decimal('0.3')
    receipt = BudgetLedger(tmp_path / 'budget.db').reserve('r', 't', DAY, lane, 100, 100, BIG, BIG)
    assert Decimal(receipt['reserved_cost']) == Decimal('0.3')


# ---- provider level: the request-derived estimate against the same ceilings --------------------------

ESTIMATE = 131  # independent pin: len(json bytes of request()) == 115, plus max_tokens 16


def request(**overrides):
    result = {'model': 'fixture-boundary', 'messages': [{'role': 'user', 'content': 'owned synthetic input'}],
              'max_tokens': 16}
    result.update(overrides)
    return result


def provider(tmp_path, ledger=None, lane=ZERO, **overrides):
    args = dict(ledger=ledger or BudgetLedger(tmp_path / 'budget.db'), lane=lane, task='owned',
                task_tokens=10 ** 6, task_cost=Decimal(0), daily_cost=Decimal(0), output_tokens=16,
                available=lambda: True, attempts=100, provider='custom', base_url='http://127.0.0.1:12345/v1')
    args.update(overrides)
    return BoundedProvider(**args)


def dispatch(route, payload, next_call):
    return route(payload, next_call, provider=route.provider, base_url=route.base_url)


def forbidden(_):
    raise AssertionError('Denied provider request reached I/O')


def stored(path):
    with sqlite3.connect(path) as db:
        return db.execute('SELECT request,day,tokens,cost,state FROM reservations ORDER BY request').fetchall()


def test_request_estimate_is_the_json_bytes_plus_the_output_ceiling():
    assert token_ceiling(request(), 16) == ESTIMATE
    assert token_ceiling(request(max_tokens=1), 16) == 115  # 114 json bytes + 1
    assert token_ceiling(request(max_tokens=16, messages=[{'role': 'user', 'content': 'é'}]), 16) \
        == len(json.dumps(request(messages=[{'role': 'user', 'content': 'é'}]), ensure_ascii=False).encode()) + 16


@pytest.mark.parametrize('ceiling_offset,allowed', [(0, True), (-1, False), (1, True)])
def test_provider_task_token_ceiling_at_the_exact_request_estimate(tmp_path, ceiling_offset, allowed):
    route = provider(tmp_path, task_tokens=ESTIMATE + ceiling_offset)
    if allowed:
        assert dispatch(route, request(), lambda _: 'ok') == 'ok'
    else:
        with pytest.raises(RouteStopped):
            dispatch(route, request(), forbidden)
        assert route.receipts == [] and stored(tmp_path / 'budget.db') == []


def test_provider_task_token_ceiling_is_cumulative_at_exactly_two_requests(tmp_path):
    route = provider(tmp_path, task_tokens=2 * ESTIMATE)
    assert dispatch(route, request(), lambda _: 'ok') == 'ok'
    assert dispatch(route, request(), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    assert len(stored(tmp_path / 'budget.db')) == 2


def test_provider_task_token_ceiling_one_below_two_requests_denies_the_second(tmp_path):
    route = provider(tmp_path, task_tokens=2 * ESTIMATE - 1)
    assert dispatch(route, request(), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)


@pytest.mark.parametrize('instant', ['2026-11-09T23:59:59+00:00', '2026-11-10T00:00:01+00:00'])
@pytest.mark.parametrize('offset,allowed', [(0, True), (-1, False)])
def test_provider_cost_ceilings_at_the_exact_priced_estimate_on_a_frozen_day(tmp_path, monkeypatch, instant, offset, allowed):
    monkeypatch.setattr(provider_execution, 'datetime', FrozenClock(instant))
    cost = Decimal(ESTIMATE) / Decimal(1000)  # independent: 131 tokens * 0.001
    for field in ('task_cost', 'daily_cost'):
        ceilings = dict(task_cost=BIG, daily_cost=BIG)
        ceilings[field] = cost if offset == 0 else cost - Decimal('1E-12')
        route = provider(tmp_path, ledger=BudgetLedger(tmp_path / (field + '.db')), lane=PRICED, **ceilings)
        if allowed:
            assert dispatch(route, request(), lambda _: 'ok') == 'ok'
            assert Decimal(route.receipts[0]['reserved_cost']) == cost
        else:
            with pytest.raises(RouteStopped):
                dispatch(route, request(), forbidden)
            assert route.receipts == []


def test_provider_hands_each_cost_ceiling_to_its_own_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_execution, 'datetime', FrozenClock('2026-11-09T12:00:00+00:00'))
    cost = Decimal(ESTIMATE) / Decimal(1000)
    ledger = BudgetLedger(tmp_path / 'budget.db')
    # daily binds, task does not: a second TASK on the same day is denied
    one = provider(tmp_path, ledger=ledger, lane=PRICED, task='daily-a', task_cost=BIG, daily_cost=cost)
    two = provider(tmp_path, ledger=ledger, lane=PRICED, task='daily-b', task_cost=BIG, daily_cost=cost)
    assert dispatch(one, request(), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(two, request(), forbidden)
    # task binds, daily does not: the same task is denied a second request, another task is not
    ledger = BudgetLedger(tmp_path / 'budget2.db')
    one = provider(tmp_path, ledger=ledger, lane=PRICED, task='task-a', task_cost=cost, daily_cost=BIG)
    two = provider(tmp_path, ledger=ledger, lane=PRICED, task='task-b', task_cost=cost, daily_cost=BIG)
    assert dispatch(one, request(), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(one, request(), forbidden)
    assert dispatch(two, request(), lambda _: 'ok') == 'ok'


def test_provider_hands_the_token_ceiling_to_the_task_token_limit_not_the_output_limit(tmp_path):
    route = provider(tmp_path, task_tokens=ESTIMATE - 1, output_tokens=10 ** 6)
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    route = provider(tmp_path, ledger=BudgetLedger(tmp_path / 'other.db'), task_tokens=10 ** 6, output_tokens=16)
    assert dispatch(route, request(), lambda _: 'ok') == 'ok'


@pytest.mark.parametrize('limit_offset,allowed', [(0, True), (1, False), (-1, True)])
@pytest.mark.parametrize('key', ['max_tokens', 'max_completion_tokens', 'max_output_tokens'])
def test_output_token_ceiling_is_exact_for_every_accepted_parameter_name(key, limit_offset, allowed):
    payload = {'model': 'fixture-boundary', 'messages': [{'role': 'user', 'content': 'x'}], key: 16 + limit_offset}
    if allowed:
        assert token_ceiling(payload, 16) == len(json.dumps(payload, ensure_ascii=False).encode()) + 16 + limit_offset
    else:
        with pytest.raises(PermissionError, match='output token ceiling'):
            token_ceiling(payload, 16)


@pytest.mark.parametrize('value', [0, -1, True, 16.0, '16', None])
def test_output_token_ceiling_rejects_nonpositive_and_non_int_values(value):
    with pytest.raises(PermissionError, match='output token ceiling'):
        token_ceiling(request(max_tokens=value), 16)


def test_output_token_ceiling_requires_exactly_one_parameter():
    both = request(max_completion_tokens=16)
    with pytest.raises(PermissionError, match='output token ceiling'):
        token_ceiling(both, 16)
    none = request()
    del none['max_tokens']
    with pytest.raises(PermissionError, match='output token ceiling'):
        token_ceiling(none, 16)


def test_provider_denies_one_over_the_output_ceiling_before_any_reservation_or_io(tmp_path):
    route = provider(tmp_path, output_tokens=16)
    assert dispatch(route, request(max_tokens=16), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(route, request(max_tokens=17), forbidden)
    assert len(stored(tmp_path / 'budget.db')) == 1


@pytest.mark.parametrize('attempts', [1, 2, 3])
def test_provider_attempt_cap_allows_exactly_n_dispatches_and_denies_the_next(tmp_path, attempts):
    route = provider(tmp_path, attempts=attempts)
    for _ in range(attempts):
        assert dispatch(route, request(), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    assert len(stored(tmp_path / 'budget.db')) == attempts


def test_provider_attempt_cap_of_zero_denies_the_first_dispatch(tmp_path):
    with pytest.raises(RouteStopped):
        dispatch(provider(tmp_path, attempts=0), request(), forbidden)


def test_a_failed_dispatch_consumes_an_attempt(tmp_path):
    route = provider(tmp_path, attempts=2)

    def fails(_):
        raise TimeoutError('owned fixture timeout')

    with pytest.raises(TimeoutError):
        dispatch(route, request(), fails)
    assert dispatch(route, request(), lambda _: 'ok') == 'ok'
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)


@pytest.mark.parametrize('instant,day', [('2026-11-09T23:59:59+00:00', '2026-11-09'),
                                        ('2026-11-10T00:00:01+00:00', '2026-11-10'),
                                        ('2026-11-09T23:30:00-05:00', '2026-11-10'),   # 04:30 UTC next day
                                        ('2026-11-10T00:30:00+05:00', '2026-11-09')])  # 19:30 UTC previous day
def test_accounting_day_is_the_utc_date_of_the_injected_clock(tmp_path, monkeypatch, instant, day):
    monkeypatch.setattr(provider_execution, 'datetime', FrozenClock(instant))
    route = provider(tmp_path)
    dispatch(route, request(), lambda _: 'ok')
    assert [row[1] for row in stored(tmp_path / 'budget.db')] == [day]


def test_daily_ceiling_rolls_over_at_utc_midnight_but_task_ceilings_do_not(tmp_path, monkeypatch):
    clock = FrozenClock('2026-11-09T23:59:59+00:00')
    monkeypatch.setattr(provider_execution, 'datetime', clock)
    cost = Decimal(ESTIMATE) / Decimal(1000)
    ledger = BudgetLedger(tmp_path / 'budget.db')
    first = provider(tmp_path, ledger=ledger, lane=PRICED, task='task-a', task_cost=cost, daily_cost=cost)
    assert dispatch(first, request(), lambda _: 'ok') == 'ok'
    second = provider(tmp_path, ledger=ledger, lane=PRICED, task='task-b', task_cost=BIG, daily_cost=cost)
    with pytest.raises(RouteStopped):  # still 2026-11-09: the daily ceiling is spent
        dispatch(second, request(), forbidden)
    clock.set('2026-11-10T00:00:01+00:00')
    assert dispatch(second, request(), lambda _: 'ok') == 'ok'  # new UTC day: a fresh daily ceiling
    first.daily_cost = BIG  # only task-a's own ceiling can deny now
    with pytest.raises(RouteStopped):  # and that one is cumulative across days
        dispatch(first, request(), forbidden)
