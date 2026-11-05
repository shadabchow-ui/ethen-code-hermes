"""Independent provider dispatch denial and real loopback SDK failure contracts."""
from decimal import Decimal

from openai import OpenAI, APITimeoutError, RateLimitError
import pytest

from ethen.code.provider_execution import BoundedProvider, RouteStopped
from ethen.code.routing import BudgetLedger, Lane
from tests.fakes.fake_llm_provider import Error, FakeLLMServer, Hang


def provider(tmp_path, **overrides):
    args = dict(ledger=BudgetLedger(tmp_path / 'budget.db'), lane=Lane('synthetic', 'fake-model', Decimal(0), Decimal(0), True, True), task='owned', task_tokens=100000, task_cost=Decimal(0), daily_cost=Decimal(0), output_tokens=16, available=lambda: True, attempts=3, provider='custom', base_url='http://127.0.0.1:12345/v1')
    args.update(overrides)
    return BoundedProvider(**args)


def request(**overrides):
    result = {'model': 'fake-model', 'messages': [{'role': 'user', 'content': 'owned synthetic input'}], 'max_tokens': 16}
    result.update(overrides)
    return result


def dispatch(route, payload, next_call, **overrides):
    context = dict(provider=route.provider, base_url=route.base_url)
    context.update(overrides)
    return route(payload, next_call, **context)


def forbidden(_):
    raise AssertionError('Denied provider request reached I/O')


def test_unknown_pricing_denies_before_next_call(tmp_path):
    route = provider(tmp_path, lane=Lane('unpriced', 'fake-model', None, None, True))
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)


def test_unavailable_provider_never_tries_expensive_fallback(tmp_path):
    route = provider(tmp_path, available=lambda: False)
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    assert route.receipts == []


def test_cancellation_revokes_future_dispatch(tmp_path):
    route = provider(tmp_path)
    route.cancel()
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)


@pytest.mark.parametrize('override', [{'model': 'unapproved-model'}, {'max_tokens': 17}, {'max_tokens': True}, {'max_completion_tokens': 8}, {'max_tokens': 0}])
def test_unauthorized_model_or_output_ceiling_never_reaches_provider(tmp_path, override):
    route = provider(tmp_path)
    with pytest.raises(RouteStopped):
        dispatch(route, request(**override), forbidden)


def test_provider_task_token_exhaustion_prevents_second_effect(tmp_path):
    route = provider(tmp_path, task_tokens=200)
    effects = []
    dispatch(route, request(), lambda _: effects.append('first'))
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)
    assert effects == ['first']


def test_provider_attempt_ceiling_prevents_second_effect(tmp_path):
    route = provider(tmp_path, attempts=1)
    dispatch(route, request(), lambda _: None)
    with pytest.raises(RouteStopped):
        dispatch(route, request(), forbidden)


@pytest.mark.parametrize('reply,exception,state', [(Error(429, 'owned rate limit'), RateLimitError, 'rate_limited'), (Hang(seconds=10), APITimeoutError, 'timeout')])
def test_real_loopback_sdk_error_has_no_retry_or_fallback(tmp_path, reply, exception, state):
    with FakeLLMServer(aux=lambda _: reply) as server:
        route = provider(tmp_path, base_url=server.base_url)
        with OpenAI(base_url=server.base_url, api_key='owned-nonsecret-fixture', max_retries=0, timeout=2.0) as client:
            with pytest.raises(exception):
                dispatch(route, request(), lambda r: client.chat.completions.create(**r))
        assert len(server.requests) == 1
    assert route.receipts[-1]['state'] == state


@pytest.mark.parametrize('context', [{'provider': 'expensive-fallback'}, {'base_url': 'https://unapproved.example/v1'}])
def test_same_model_name_does_not_authorize_another_provider_or_origin(tmp_path, context):
    with pytest.raises(RouteStopped):
        dispatch(provider(tmp_path), request(), forbidden, **context)


def test_cancellation_discards_inflight_result(tmp_path):
    route = provider(tmp_path)

    def finishes_after_cancel(_):
        route.cancel()
        return 'stale model output'

    with pytest.raises(RouteStopped):
        dispatch(route, request(), finishes_after_cancel)
    assert route.receipts[-1]['state'] == 'cancelled'


@pytest.mark.parametrize('reply,exception,state', [(Error(429, 'owned rate limit'), RateLimitError, 'rate_limited'), (Hang(seconds=10), APITimeoutError, 'timeout')])
def test_native_middleware_preserves_sdk_error_classification(tmp_path, reply, exception, state):
    from hermes_cli.middleware import run_llm_execution_middleware
    from hermes_cli.plugins import PluginContext, PluginManifest, _delivery_manager

    with FakeLLMServer(aux=lambda _: reply) as server:
        route = provider(tmp_path, base_url=server.base_url)
        context = PluginContext(PluginManifest(name='owned-provider-review'), _delivery_manager())
        handle = context.register_middleware('llm_execution', route)
        try:
            with OpenAI(base_url=server.base_url, api_key='owned-nonsecret-fixture', max_retries=0, timeout=2.0) as client:
                with pytest.raises(exception):
                    run_llm_execution_middleware(request(), lambda r: client.chat.completions.create(**r), provider='custom', base_url=server.base_url)
        finally:
            handle.dispose()
        assert len(server.requests) == 1
    assert route.receipts[-1]['state'] == state


def test_native_middleware_cannot_fall_open_when_budget_denies(tmp_path):
    from hermes_cli.middleware import run_llm_execution_middleware
    from hermes_cli.plugins import PluginContext, PluginManifest, _delivery_manager

    route = provider(tmp_path, task_tokens=1)
    context = PluginContext(PluginManifest(name='owned-provider-denial-review'), _delivery_manager())
    handle = context.register_middleware('llm_execution', route)
    try:
        with pytest.raises(RouteStopped):
            run_llm_execution_middleware(request(), forbidden, provider='custom', base_url=route.base_url)
    finally:
        handle.dispose()


@pytest.mark.parametrize('override', [
    {'n': 2}, {'n': True},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.invalid/image'}}]}]},
])
def test_unpriced_multiple_generation_or_multimodal_request_is_denied(tmp_path, override):
    with pytest.raises(RouteStopped):
        dispatch(provider(tmp_path), request(**override), forbidden)
