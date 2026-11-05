# Hermes-native owned coding workflow — EV6-045

This is a fresh, synthetic qualification consumer of Hermes, not another agent
runtime or a released coding service. EV6-044 source and the existing UI are
unchanged. Real autonomous model quality remains **UNVERIFIED**.

The owned issue assignment selects one disposable repository, creates a local
working branch, and runs Hermes `AIAgent` against its existing loopback
`FakeLLMServer`. Real file/terminal tools read the source, report failing tests,
request one exact native ACP edit, rerun tests, produce a Git diff and review,
and retain native `SessionDB` history plus an atomic completion receipt.
No push, merge or deployment tool command is authorized.

## Boundaries

The Linux launcher requires rootlesskit, a private loopback-only network namespace,
no-new-privileges, Landlock read/write confinement and an existing operator-owned
scope capped at 2200 MiB memory, zero swap and at most two CPUs. It creates only
owned synthetic fixtures, scrubs inherited Git configuration before Git operations,
and refuses policy-bypass worker mode. The selected source is a sanitized fixture;
a secret symlink resolves outside its read allowlist, as does another session's
private file. Native atomic replacement writes remain readable inside the owned
project. The policy separately denies secret names, symlinks, other repositories,
unapproved shell commands, tool types and nonmatching/replayed edit payloads.

This does **not** authorize arbitrary host repository code, imported plugins,
production credentials, real model calls or a multi-tenant service. Runtime source
and interpreter dependencies are readable for execution. A production repository
sanitizer, controller/service identity and separate privilege domains require
further authorization/qualification; a tool gate is not a substitute for those.

## Routing and receipts

`Lane` and `BoundedProvider` accept explicit operator configuration for local,
economical API or fallback lanes. Each lane requires approval, a model identity,
finite known input/output prices, an exact provider/origin binding, availability
checking, output ceilings and task/day limits. No fallback is automatic. The
qualification enables only the owned synthetic lane at zero spend and disables
SDK retries. It checks that every fixture request has a budget receipt.

The SQLite ledger atomically reserves conservative JSON/text token and cost
ceilings before each request. Concurrent requests, restarts and uncertain failures
cannot refund a reservation or reuse an effect identifier. Unknown pricing,
provider redirection, multimodal or multiple-generation pricing, exhaustion and
cancellation stop the owned worker before dispatch. Native middleware errors do
not turn authorization denial into an unguarded request. 429 and timeout outcomes
remain charged conservatively and are recorded without expensive retry/fallback.

Use one operator-controlled ledger across tasks for a shared daily limit. The
isolated qualification uses its own zero-cost ledger; it does not claim an enabled
production billing service. Provider-reported usage is separate from reserved
estimates; synthetic usage is labeled, and actual billed cost is not invented.
Local/Ollama and paid-provider inference have not been activated or evaluated.

Completion and its receipt commit together. A fresh confined process can return
an unchanged completed receipt after checking source, branch, diff and native
history, without dispatching again. A crash after an edit but before completion
leaves a durable reservation: restart refuses ambiguous redispatch and preserves
the source/history for operator reconciliation. It does not silently replay edits.

Operator cancellation revokes grants, interrupts the native agent and cleans up
native terminal environments. The Linux test proves that its running owned child
is reaped. Cancellation discards stale provider results.

## Replay

Use the existing qualified Hermes test interpreter, not a raw pip-modified runtime.
From this source inside an operator-owned resource scope:

```sh
HERMES_PYTHON=/existing/test/bin/python HERMES_RUN_E2E=1 \
  bash scripts/run_tests.sh -j 1 --file-retries 0 --file-timeout 180 \
  tests/ethen/test_native_workflow.py tests/ethen/test_routing_budget.py \
  tests/ethen/test_repository_boundary.py tests/ethen/test_provider_execution.py \
  -pno:cacheprovider -v
```

The native file creates separate disposable cases for success/restart, actual
post-edit crash/restart denial, and cancellation/process cleanup. The other files
exercise real native middleware, ACP proposals and loopback SDK 429/timeouts.
Model responses are synthetic; passing these tests is not real model-quality,
EV6-046 packaging, hosted-runner or milestone-closure evidence.
