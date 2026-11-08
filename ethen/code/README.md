# Ethen Code: Hermes-native local qualification

Hermes Agent is the sole runtime foundation for Ethen Code. The canonical fork is
`shadabchow-ui/ethen-code-hermes`. Base `5e7c2b254d414e4e25105231f818f385fee67469`
was fetched directly from `NousResearch/hermes-agent`; upstream MIT LICENSE and
history remain intact. UI PR #1, `bdeda596ab6ee7f503992294605a3e3087049646`, is the
parent of this work. Its nine Foundation/theme files are preserved byte for byte.
Only Hermes is pinned. The historical OpenCode repository (`shadabchow-ui/ethen-code-oc`)
is an **owner decision**, not an established fact: it is treated as an unchanged archive,
not pinned or re-verified here (private repository unreadable without credentials).
This repository has no runtime, compatibility layer, source import or migration
dependency on it; `tests/ethen/test_upstream_pins.py` scans for such references.

`qualification.py` is a public, synthetic-only consumer of existing Hermes
interfaces. It is deliberately not an agent service, new tool implementation or
production permission system. It runs `run_agent.AIAgent` through the real HTTP
SDK against Hermes' existing `tests.fakes.fake_llm_provider.FakeLLMServer`, then
uses the actual tool dispatcher, file tools, terminal backend and `SessionDB`.
There are no mocked tool results or model-quality claims. The fake key is a
non-secret fixture value; only the owned loopback server receives it.

The disposable Git repository starts with a deliberately broken `add()` and three
owned tests. Hermes reads the repository, observes failing tests, attempts an
unauthorized test-file write (denied by native ACP edit approval), applies one
exact authorized patch, passes the tests and reviews the Git diff. A terminal
write outside the kernel allowlist must fail. The native session database is
closed and reopened, and its resumed conversation must contain the actual tool
results. The workflow produces a transcript and review receipt with a transcript
SHA-256, real exit codes, changed files and explicit synthetic/model status.

`EditGrant` consumes the native ACP `EditProposal` interface, binds the exact file,
old/new payload and tool, and denies changed, replayed, symlinked, multi-file or
cancelled requests. Its single-use transition is atomic. It never sets `force`,
disables an upstream guard or grants permanent approval. Cancellation is checked
with native interrupt contracts; this qualification does not claim a tested
production STOP UI or cancellation of every provider transport.

## Reproduce safely

Use an existing approved Linux machine with Python 3.14 and a disposable test
environment prepared through Hermes PM. No raw pip mutation of a Hermes runtime
is needed. The qualification uses a narrowly selected subset of the unchanged
`pyproject.toml`/`uv.lock`, including the declared ACP extra, pytest and pinned Ruff;
the exact installed inventory and selection are retained in the acceptance evidence.
No model packages, weights, GPU or provider credentials are required.

On a disposable checkout snapshot, invoke the launcher under the existing heavy
job lock and an owned resource scope. For example, with operator-approved paths:

```sh
flock -n "$existing_heavy_lock" systemd-run --user --scope \
  --property=MemoryMax=2200M --property=MemorySwapMax=0 --property=CPUQuota=170% \
  bash ethen/code/run-isolated.sh "$new_owned_output" "$existing_test_python"
```

The output directory must not exist. `rootlesskit` creates a private mount/user
namespace; only there is an owned scratch directory bound over `/var/tmp`.
`unshare --net` exposes loopback only. Landlock permits direct filesystem writes only to
owned home, scratch and evidence paths plus the canonical runner ignored duration-cache
file; source and unrelated host paths are write-denied for that class of operation.
The cgroup scope caps memory, swap and CPU; it is not isolation.

**What this envelope does not do.** It is a guard for the scripted fixture, not a
security boundary. It is unsuitable for untrusted code, confidentiality, multi-tenancy
or the hosted runtime isolation that EV6-045 and EV6-046 require.

- Landlock here restricts direct filesystem writes (content and namespace operations) only.
  It does not confine reads (all of `/` is readable, including home-directory secrets).
- It does not confine unix-socket IPC. Connecting to the user D-Bus and the rootless Docker
  sockets was proven to give an unconfined escape: a transient `systemd-run --user` unit
  created a file outside the write allowlist.
- It does not confine signals to same-uid host processes (the pid namespace is the host one)
  or metadata changes (chmod, utime, xattrs, flock).
- The process is uid 0 inside its user namespace and holds namespaced capabilities;
  only Landlock mount/ptrace hooks and no-new-privs limit them.
- Network isolation is the network namespace alone (loopback only). Landlock network rights
  are not used, and the unix-socket paths above bypass it.
- The Landlock rules come from a coordinator-written, non-upstream user-space stand-in for
  util-linux 2.40 `setpriv --landlock-*`, valid only on the qualification host (kernel 6.8,
  Landlock ABI 4, util-linux 2.39, whose own `setpriv` has no Landlock support).
  Run evidence: `evidence/ev6-044-q3` (outside this repository); the escape and signal
  findings are from the independent review probes recorded with the EV6-044 evidence.

The fixture refuses to start unless no-new-privileges, loopback-only networking and
the owned outside-write denial and kernel memory/swap/CPU limits are verified. The launcher records actual cgroup
limits/peak/events and unmounts its scratch directory on exit.

All Python tests run through `scripts/run_tests.sh`, with credentials scrubbed,
isolated Hermes profiles, one worker, no flaky retries and a 150-second file limit.
The integration case uses upstream's existing `HERMES_RUN_E2E=1` switch. An ordinary
suite run leaves that case explicitly skipped; a local acceptance run must execute
it without a skip. The focused set also exercises native ACP permission
missing/denied/timeout outcomes, edit approvals and interrupt compatibility.

## Scope and remaining boundaries

Model routing is a qualification contract: only `fake-model`, an exact numeric
loopback HTTP origin and zero permitted spend are accepted. Within the fixture, the network namespace (loopback only) keeps the SDK and
auxiliary paths off the host network; it is not a barrier against hostile code
(see the sandbox limits above). Actual model execution remains **UNVERIFIED**.
No paid provider, external teacher/model API, public listener or production
configuration is enabled. Full routing, policy/budget integration and hosted
runtime isolation belong to EV6-045; production coding services and release
acceptance remain EV6-046. A generic agent loop does not establish those jobs.

The unchanged Foundation UI's production webapp build and 71-test receipt at
PR #1 are reusable. Exact UI hashes, independent receipt and generator output
are reconciled separately; no fresh full renderer build or native Electron
launch is implied. Prior build memory headroom was tight (2.2 GiB cap, no OOM).

Only generic qualification code and owned synthetic fixtures are added to this
public fork. No private Upcube code, secrets or proprietary product implementation
is imported. No new remote repository, push, PR mutation, Actions, merge or
deployment is part of this local acceptance.
