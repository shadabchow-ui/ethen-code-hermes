# Ethen Code local CLI package

This Linux CPython 3.14 source-prefix package exposes the EV6-045 owned synthetic
coding workflow through Hermes' native payload launcher and PM dependency builder.
It is not a wheel, signed release, arbitrary-repository coding service or a new shell.
Hermes and upstream MIT attribution remain in the complete source artifact.

## Build and install

Seal a Git commit, then from that checkout:

```sh
python3 -m ethen.code.build_package --commit <exact-sha> --out /owned/path/ethen-code.tar.gz
sha256sum /owned/path/ethen-code.tar.gz
```

The archive contains exactly the commit's tracked source, including the synthetic
provider fixture and existing Desktop/UI, plus source SHA/tree provenance. Sorted
Git entries and fixed tar/gzip metadata make repeated builds byte-identical. It has
no bundled native interpreter, downloaded model or secret. Verify its SHA256 from
your independently trusted receipt before extracting into a new owned directory.

Installation requires an explicitly supplied existing Linux CPython 3.14 interpreter,
Hermes' already staged pinned runtime tools and an offline PM dependency cache for
the unchanged uv.lock. No browser, model weights, Node, system tool or service is
installed automatically. With the staged tool location configured via native
HERMES_RUNTIME_DIR, run inside the extracted artifact:

```sh
python3.14 -B -m ethen.code.package install --prefix /new/owned/ethen-code \
  --python /existing/bin/python3.14 --cache /existing/pm-cache
/new/owned/ethen-code/bin/ethen-code --help
```

PM builds a fresh frozen, sealed, offline dependency environment, preserving the
existing one. The native launcher resolves only installed source/dependencies;
it does not depend on the author checkout. This is a fixed-prefix installation,
with an explicitly referenced external interpreter, not a portable binary bundle.
installation.json records source identity, lock hashes and runtime version.

## Local session

System prerequisites: systemd user manager, rootlesskit, unshare, ip, Git, Bash and
setpriv with Landlock. Unprivileged namespaces, Landlock and user cgroups must work.
The CLI creates its worker in a 2200 MiB / zero-swap / 170% CPU user scope and private
network namespace. Missing prerequisites stop execution; there is no sandbox bypass.

```sh
ethen-code init --session /new/owned/session
ethen-code run --session /new/owned/session --repo /new/owned/session/project
ethen-code receipt --session /new/owned/session
ethen-code resume --session /new/owned/session
ethen-code stop --session /new/owned/session
```

init creates a fresh disposable Git repository. Repository selection is explicitly
limited to that session's unchanged owned fixture; it never imports arbitrary host
code. The real native ACP callback shows the exact proposal and requires the word
approve. EOF or another answer denies. The console prints actual file/terminal
results, failing/green test exit codes, Git diff and structured review receipt.
Denial leaves source intact and fences ambiguous retries. Resume validates durable
native source/history without dispatching completed work again. Stop uses a Linux
pidfd with recorded process start identity to avoid signaling a recycled PID.
Ctrl-C also requests native cleanup. --scenario cancel/crash are explicitly labeled
owned fault injections for qualification, not task-running features.

No push, merge, deploy, real provider inference or paid fallback is enabled. The
selection, exact-edit authorization, Landlock and budget checks remain authoritative.
Session artifacts/evidence live outside the installation; preserve them separately.

## Rollback and unavailable surfaces

Stop all sessions and ensure no process uses the installation. From the extracted
artifact, run `python3.14 -B -m ethen.code.package uninstall --prefix /owned/ethen-code`.
Rollback verifies the installed-file inventory, refuses modified/unknown files and
removes only the unchanged owned prefix. It preserves external sessions and receipts.
Failed installations lack a completion manifest: preserve/reconcile them rather than
assuming successful rollback. No global PATH links or services are installed.

Only Linux local operation is qualified. macOS and Windows workflow packages are
NOT_RUN. Existing Hermes Desktop/Webapp and Ethen Foundation PR #1 are preserved.
Desktop already owns project selection/approval presentation, but its gateway RPCs
do not automatically carry this ACP worker policy. The available native macOS host
cannot run the Linux confinement backend. No unqualified Desktop button, replacement
shell or public terminal was added. Native Desktop build/browser workflow smoke:
NOT_RUN. Hosted execution: NOT_RUN; requires Platform identity, separate isolated
runners and explicit deployment authorization. EV6-044/045 closure classifications,
EV6-043 HOLD and REL are unchanged by this packaging evidence.
