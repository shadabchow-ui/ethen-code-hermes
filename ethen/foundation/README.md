# Ethen Foundation adapter for Hermes Desktop and Webapp

Source: shadabchow-ui/ethen-v6-foundation `ff-m04/integration` at `0f640c0826fb34347fc9b4a72f9282a33f5e5270`, tokens/ethen.tokens.json `ethen.tokens/0.1.3`. Canonical token status remains PROPOSED, not visual/IP clearance. The byte-preserved JSON snapshot and generated shared TypeScript export are pinned; update both together from the canonical source, never hand-edit generated color values.

The actual existing Hermes preset registry now includes Ethen. Choose it through Appearance or native `/skin ethen`; the same actual renderer feeds Electron and `build:webapp`. No default or saved user selection is overwritten. Light/dark modes use Foundation colors through existing shadcn slots; text buttons and input controls adopt its radius, and control motion preserves reduced-motion preferences. Existing terminal/editor/repo/test/review/session/native CLI capabilities remain in upstream source unchanged. No substitute shell or fake agent backend is introduced.

Only the theme/control UI slice is implemented here. No inference, benchmark, production Platform authority binding, gateway architecture replacement, credential modification, deployment or release acceptance is claimed. OpenCode remains HOLD. MIT upstream license is preserved.

Regenerate the shared export after a reviewed snapshot update with `node ethen/foundation/sync.mjs --write`; `--check` verifies it without modifying source. No network or font fetch is performed by this adapter.

Compatibility scope: this optional Foundation 0.1.3 warm/indigo preset is not a new global palette authority and does not replace the separately approved Platform monochrome styling. Existing Hermes default and every saved/user preset remain unchanged.
