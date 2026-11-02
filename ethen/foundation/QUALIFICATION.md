# Ethen Foundation preset qualification — 2026-11-02

Implemented on authorized OVH `vps-49d9b8a0`, user `ethenjob`, from Hermes `5e7c2b254d414e4e25105231f818f385fee67469`. No Mac engineering/build/test execution was used for this slice. Full upstream source and MIT attribution remain preserved; CodeOC stays HOLD.

- Actual upstream Desktop Webapp production builder: **exit 0**, Vite 21.15 seconds, completed 22:22:17 UTC. Native Electron executable was not built/launched. This is the shared real renderer, not a replacement shell or backend mock.
- Focused actual UI regression tests: **71/71 passed across six files, exit 0**, 17.03 seconds. New tests exercise real Button/Input callbacks, Foundation light/dark state, appearance persistence and removal on switching. Existing theme context/profile/boot/typography and Input regressions also passed.
- Generator byte check, scoped ESLint/Prettier and strict typed DesktopTheme contract check: **exit 0**. Full upstream Python suite, all-workspace checks and native CLI/model benchmark were not run; no such pass is claimed.
- Every heavy run used the canonical ETHEN_V6_HEAVY.lock and its own systemd scope: CPU quota 170%, MemoryMax 2200 MiB, swap 0; final heap 1280 MiB. Final build cgroup memory.peak **2306867200 bytes**, OOM/kill 0; test peak **665931776 bytes**, OOM/kill 0. Build touched its memory cap and retains tight memory headroom. Both filesystems remained above 10 GiB; final guarded runs used an 11 GiB stop buffer.
- Earlier failures retained: first owned install stopped before disk-floor breach and its partial workspace/cache relocated between owned scratch directories; 1792 MiB heap build compiled but stalled under cgroup reclaim and was stopped (not PASS); a cosmetic generated filename change invalidated dependency fingerprint and was reverted without reinstalling; lint string escaping and generator numeric formatting checks were fixed with their failed logs preserved. Source effects and limits were not weakened.

Upstream product receipt:

```json
{
  "schema": 1,
  "product": "webapp",
  "platform": "linux",
  "arch": "x64",
  "node": "26.12.1",
  "inputs": {
    "sourceHash": "63605951c2a27ed239b70bd2b15e1c8a7cf191fcf47ecbe0513687c2e995b727",
    "prepared": [],
    "env": [
      [
        "NODE_ENV",
        "production"
      ]
    ]
  },
  "outputHash": "e46bacb986b1e692fab523acc795a58a321e37dbebf24fa587bbb03aca255e84"
}
```

Evidence on the same existing host: `/mnt/ethen-data/code-hermes-qualification-20261102/evidence/` (build/test/check logs and exits, kernel cgroup measurements, retained failures and Foundation source checksum). These are author-run OVH results. **Independent review/reproduction pending**, no release job accepted and no live Platform identity/policy/vault/billing/execution integration claimed.

No paid model calls, benchmark runs, new VM, Actions, public runtime, merge, deployment, DNS/secret changes or production database work. The preset is opt-in and explicitly does not replace Platform monochrome authority or existing Hermes defaults. Normal terminal/repo/test/review/session/native CLI source remains unchanged; its full end-to-end runtime acceptance is outside this presentation slice.
