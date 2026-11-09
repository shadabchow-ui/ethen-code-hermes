"""Local, synthetic fail-closed spend contracts for the EV6-045 provider gate.

Closes gaps found while mapping the acceptance contract: the existing provider tests only use a
zero-price synthetic lane, so cost ceilings, unapproved lanes, the loopback (local/Ollama-style)
availability probe and receipt labelling were proven only at ledger level or not at all.
No network, no real model, no credentials: loopback sockets owned by the test only.
"""
from decimal import Decimal
from types import SimpleNamespace
import socket

import pytest

from ethen.code.provider_execution import BoundedProvider, RouteStopped, loopback_available, token_ceiling
from ethen.code.routing import BudgetLedger, Lane

CHEAP_API = dict(name='cheap-api', model='fixture-cheap', input_per_million=Decimal('0.15'),
                 output_per_million=Decimal('0.60'), approved=True)


def request(**overrides):
    result = {'model': 'fixture-cheap', 'messages': [{'role': 'user', 'content': 'owned synthetic input'}], 'max_tokens': 16}
    result.update(overrides)
    return result


def provider(tmp_path, ledger=None, task='owned', **overrides):
    args = dict(ledger=ledger or BudgetLedger(tmp_path / 'budget.db'), lane=Lane(**CHEAP_API), task=task,
                task_tokens=100000, task_cost=Decimal(1), daily_cost=Decimal(1), output_tokens=16,
                available=lambda: True, attempts=10, provider='custom', base_url='http://127.0.0.1:12345/v1')
    args.update(overrides)
    return BoundedProvider(**args)


def dispatch(route, payload, next_call):
    return route(payload, next_call, provider=route.provider, base_url=route.base_url)


def forbidden(_):
    raise AssertionError('Denied provider request reached I/O')


def one_request_cost():
    return Lane(**CHEAP_API).ceiling(token_ceiling(request(), 16))


def test_cost_ceiling_is_enforced_at_the_provider_before_io_with_an_exact_boundary(tmp_path):
    cost = one_request_cost()
    assert cost > 0
    effects = []
    assert dispatch(provider(tmp_path, task_cost=cost), request(), lambda _: effects.append('io') or 'ok') == 'ok'
    assert effects == ['io']
    for index, ceiling in enumerate((cost - Decimal('0.0000000001'), Decimal(0))):
        route = provider(tmp_path, ledger=BudgetLedger(tmp_path / ('denied%d.db' % index)), task_cost=ceiling, daily_cost=Decimal(1))
        with pytest.raises(RouteStopped):
            dispatch(route, request(), forbidden)
        assert route.receipts == []


def test_daily_cost_ceiling_spans_tasks_through_the_provider(tmp_path):
    ledger = BudgetLedger(tmp_path / 'shared.db')
    cost = one_request_cost()
    first = provider(tmp_path, ledger=ledger, task='task-a', daily_cost=cost)
    assert dispatch(first, request(), lambda _: 'ok') == 'ok'
    second = provider(tmp_path, ledger=ledger, task='task-b', daily_cost=cost)
    with pytest.raises(RouteStopped):
        dispatch(second, request(), forbidden)


@pytest.mark.parametrize('approved', [False, 1, 'yes', None])
def test_known_prices_without_a_true_boolean_approval_never_reach_the_provider(tmp_path, approved):
    route = provider(tmp_path, lane=Lane(**dict(CHEAP_API, approved=approved)))
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    assert route.receipts == []


def test_failed_dispatch_stays_charged_and_a_second_request_is_denied_not_retried(tmp_path):
    route = provider(tmp_path, task_cost=one_request_cost())
    calls = []

    def fails(_):
        calls.append('io')
        raise TimeoutError('owned fixture timeout')

    with pytest.raises(TimeoutError):
        dispatch(route, request(), fails)
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    assert calls == ['io']
    assert [r['state'] for r in route.receipts] == ['timeout']


def _listening_port():
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(64)  # probes connect without accepting: a tiny backlog would silently turn later True results into timeouts
    return server


def test_local_lane_availability_probe_accepts_only_a_listening_numeric_loopback_http_origin():
    with _listening_port() as server:
        port = server.getsockname()[1]
        assert loopback_available('http://127.0.0.1:%d' % port) is True
        assert loopback_available('http://127.0.0.1:%d/v1' % port) is True
        for url in ('http://localhost:%d' % port, 'https://127.0.0.1:%d' % port, 'http://[::1]:%d' % port,
                    'http://0.0.0.0:%d' % port, 'http://127.0.0.1', 'http://192.0.2.1:%d' % port,
                    'ftp://127.0.0.1:%d' % port, ''):
            assert loopback_available(url) is False, url
    assert loopback_available('http://127.0.0.1:%d' % port) is False  # closed again: unavailable, never a fallback


def test_unavailable_local_lane_denies_before_io_even_when_a_cheap_api_lane_is_priced_and_approved(tmp_path):
    route = provider(tmp_path, available=lambda: loopback_available('http://localhost:11434'))
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)


@pytest.mark.parametrize('synthetic,kind', [(True, 'SYNTHETIC_PROVIDER_REPORT'), (False, 'PROVIDER_REPORT')])
def test_receipt_labels_reported_usage_and_never_invents_a_billed_cost(tmp_path, synthetic, kind):
    route = provider(tmp_path, lane=Lane(**dict(CHEAP_API, synthetic=synthetic)))
    reported = {'prompt_tokens': 7, 'completion_tokens': 3}
    dispatch(route, request(), lambda _: SimpleNamespace(usage=reported))
    receipt = route.receipts[-1]
    assert receipt['state'] == 'completed'
    assert receipt['provider_reported_usage'] == reported
    assert receipt['actual_billed_cost'] is None
    assert receipt['usage_kind'] == kind
    assert Decimal(receipt['reserved_cost']) == one_request_cost()
