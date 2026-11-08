"""Pins the upstream identity of the Ethen Code fork: license, brand text, CLI entry points and the reviewed UI files must not drift.

Pure file checks (no network, no model, git optional), so they run in any snapshot of the repository.
They are drift guards, NOT proof of upstream identity: the sha256 values in the pin file are self-referential, so a
consistent edit of a file plus its pin entry passes unless an anchor kept in THIS file (the commit ids, the license and
vercel.json path lists, the workspace list) changes as well. Entry-point function BODIES are only checked to be non-trivial.
"""

import ast
import functools
import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Second anchors, deliberately outside the pin file: changing a pin value alone must fail; re-pinning needs a reviewed change to this file too.
BASE_COMMIT = "5e7c2b254d414e4e25105231f818f385fee67469"
UI_PR_1_COMMIT = "bdeda596ab6ee7f503992294605a3e3087049646"
# The complete set of license/notice files (18) and of deploy-disabling vercel.json files (12), kept outside the pin file.
EXPECTED_LICENSE_FILES = (
    "LICENSE",
    "apps/desktop/src/plugins/hermes-bots/LICENSE",
    "optional-skills/creative/ai-presenter-video/LICENSE",
    "optional-skills/creative/anatomy/LICENSE.txt",
    "optional-skills/creative/auteur/LICENSE",
    "optional-skills/creative/dream-loop/LICENSE.txt",
    "optional-skills/creative/ip-as-logo/LICENSE",
    "optional-skills/creative/mono-color/LICENSE.txt",
    "optional-skills/creative/system-atlas/LICENSE.txt",
    "optional-skills/software-development/ast-grep/LICENSE",
    "optional-skills/software-development/pr-lens/LICENSE.txt",
    "optional-skills/web-development/scrollcraft/LICENSE.txt",
    "plugins/hermes-achievements/LICENSE",
    "plugins/security-guidance/LICENSE",
    "plugins/security-guidance/NOTICE",
    "skills/creative/humanizer/LICENSE",
    "skills/productivity/microsoft-office/LICENSE",
    "skills/productivity/pdf/LICENSE",
)
EXPECTED_VERCEL_JSON = (
    "apps/bootstrap-installer/vercel.json",
    "apps/desktop/electron/find-in-page-native-fixture/vercel.json",
    "apps/desktop/vercel.json",
    "apps/shared/vercel.json",
    "plugins/platforms/photon/sidecar/vercel.json",
    "scripts/whatsapp-bridge/vercel.json",
    "tests-js/vercel.json",
    "ui-tui/packages/hermes-ink/vercel.json",
    "ui-tui/vercel.json",
    "vercel.json",
    "web/vercel.json",
    "website/vercel.json",
)
PINS = json.loads((ROOT / "ethen" / "code" / "UPSTREAM_PINS.json").read_text())

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}


def _sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


@functools.lru_cache(maxsize=1)
def _repo_files() -> tuple:
    """Every file under ROOT (posix relative paths): a filesystem walk, so untracked files count, united with git ls-files when git works."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        base = Path(dirpath).relative_to(ROOT)
        found.update((base / name).as_posix() for name in filenames)
    try:
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"], stderr=subprocess.DEVNULL).decode().split("\0")
    except Exception:  # an exported snapshot has no .git: the walk alone is used
        tracked = []
    found.update(t for t in tracked if t and (ROOT / t).is_file())
    return tuple(sorted(found))


def test_pin_file_declares_hermes_as_the_only_runtime_foundation():
    assert PINS["schema"] == "ethen.code.upstream-pins/1"
    assert PINS["job"] == "EV6-044"
    assert "sole Ethen Code runtime foundation" in PINS["decision"]
    hermes = PINS["hermes"]
    assert hermes["license"] == "MIT"
    assert hermes["upstream"] == "https://github.com/NousResearch/hermes-agent"
    for key in ("pinned_base_commit", "ui_pr_1_commit", "qualification_commit", "preserved_source_commit"):
        assert re.fullmatch(r"[0-9a-f]{40}", hermes[key]), key
    assert hermes["fork_main_equals_pinned_base"] is True
    assert hermes["pinned_base_commit"] == BASE_COMMIT
    assert hermes["ui_pr_1_commit"] == UI_PR_1_COMMIT
    assert PINS["hermes"]["pinned_base_date"] == "2026-11-02"
    assert BASE_COMMIT in PINS["hermes"]["ancestry_check"] and "ancestor" in PINS["hermes"]["ancestry_check"]


def test_opencode_is_recorded_as_an_unverified_owner_decision_without_a_dependency():
    oc = PINS["opencode"]
    assert oc["status"] == "OWNER_DECISION_UNCHANGED_ARCHIVE_NOT_PINNED_NOT_VERIFIED"
    assert "Nothing in this repository imports or depends on it" in oc["note"]
    assert "private" in oc["note"] and "unreadable without credentials" in oc["note"]
    decision = PINS["decision"].lower()
    assert "owner decision" in decision and "not pinned" in decision
    assert "both upstreams" not in json.dumps(PINS).lower()  # only Hermes is pinned
    pyproject = (ROOT / "pyproject.toml").read_text().lower()
    assert "ethen-code-oc" not in pyproject and "opencode" not in pyproject


def test_unchanged_upstream_files_keep_their_exact_content():
    for rel, want in PINS["unchanged_from_pinned_base"]["files"].items():
        assert _sha256(rel) == want, f"{rel} drifted from the pinned upstream content"


def test_the_upstream_mit_license_and_copyright_notice_are_intact():
    text = (ROOT / "LICENSE").read_text()
    assert text.startswith("MIT License")
    assert "Copyright (c) 2025 Nous Research" in text
    assert "Permission is hereby granted, free of charge" in text
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in text


def test_cli_entry_points_are_the_upstream_hermes_ones():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts == PINS["unchanged_from_pinned_base"]["cli_entry_points"]


def test_the_reviewed_foundation_ui_files_are_byte_identical_to_pr_1():
    for rel, want in PINS["ethen_foundation_ui_pr_1"]["files"].items():
        assert _sha256(rel) == want, f"{rel} drifted from UI PR #1"


# ---- license / notice files: case and naming variants are caught, and the set is anchored in this file ----
_LICENSE_NAME = re.compile(r"^(licen[cs]e|copying|copyright|notice|unlicense)([-_. ].*)?$", re.I)
_CODE_SUFFIX = re.compile(r"\.(py|pyi|[cm]?[jt]sx?|css|scss|sh|vue|svelte|go|rs|java|rb|php|c|h|cpp)$", re.I)  # notice-strip.tsx is UI code, not a legal notice


def _license_like(rel: str) -> bool:
    parts = rel.split("/")
    return (bool(_LICENSE_NAME.match(parts[-1])) and not _CODE_SUFFIX.search(parts[-1])) or any(re.fullmatch(r"licen[cs]es", p, re.I) for p in parts[:-1])


def test_license_name_matcher_catches_case_and_naming_variants():
    for name in ("LICENSE", "LICENCE", "LICENSE-MIT", "LICENSE_APACHE", "license.md", "License.txt", "COPYING", "COPYING.LESSER", "NOTICE.txt", "notice", "sub/dir/Licence.rst", "LICENSES/MIT.txt"):
        assert _license_like(name), name
    for name in ("agent/chat_completion_wait_notice.py", "notice-strip.tsx", "notice-owner.test.tsx", "licensed.py", "src/unlicensed.txt", "docs/noticeboard.md", "README.md"):
        assert not _license_like(name), name


def test_every_license_and_notice_file_is_pinned_and_none_added_or_removed():
    pinned = PINS["license_and_notice_files"]["files"]
    assert len(EXPECTED_LICENSE_FILES) == 18
    assert sorted(pinned) == sorted(EXPECTED_LICENSE_FILES), "pin file license list differs from the anchor list in this test"
    assert [r for r in _repo_files() if _license_like(r)] == sorted(EXPECTED_LICENSE_FILES)
    for rel, want in pinned.items():
        assert _sha256(rel) == want, f"{rel} drifted"


# ---- deploy-disabling vercel.json: the walked set of vercel config files must equal the pinned 12 ----
_VERCEL_NAME = re.compile(r"^vercel\.(json[c5]?|[cm]?[jt]s)$", re.I)


def test_the_deploy_disabling_vercel_json_files_are_exactly_the_pinned_twelve_and_unchanged():
    pinned = PINS["deploy_disabled_vercel_json"]["files"]
    assert len(EXPECTED_VERCEL_JSON) == 12
    assert sorted(pinned) == sorted(EXPECTED_VERCEL_JSON), "pin file vercel.json list differs from the anchor list in this test"
    found = [r for r in _repo_files() if _VERCEL_NAME.match(r.rsplit("/", 1)[-1])]
    assert found == sorted(EXPECTED_VERCEL_JSON), "a vercel config file was added or removed"
    for rel, want in pinned.items():
        assert _sha256(rel) == want, f"{rel} drifted"
        assert json.loads((ROOT / rel).read_text())["git"]["deploymentEnabled"] is False, rel


def test_the_workspace_manifest_is_unchanged():
    for rel, want in PINS["workspace_manifest"]["files"].items():
        assert _sha256(rel) == want
    assert json.loads((ROOT / "package.json").read_text())["workspaces"] == ["apps/*", "ui-tui", "ui-tui/packages/*", "web", "tests-js"]


# ---- CLI entry points: the target must define a callable with a non-trivial body ----
def _entry_point_problem(source: str, func: str):
    """Return None when module-level `def func` exists exactly once, is not rebound, and its body (after a docstring) makes at least one call."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"does not parse: {exc}"
    defs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func]
    if len(defs) != 1:
        return f"{func} is not defined exactly once as a module-level def"
    for node in tree.body:
        if node is defs[0]:
            continue
        names = []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [(a.asname or a.name).split(".")[0] for a in node.names]
        elif isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        if func in names:
            return f"{func} is rebound at module level"
    body = defs[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not any(isinstance(n, ast.Call) for stmt in body for n in ast.walk(stmt)):
        return f"{func} has a trivial body (no call after the docstring)"
    return None


def test_entry_point_checker_rejects_stubs_and_accepts_real_bodies():
    bad = (
        "def main(): pass\n",
        "def main(*a, **k):\n    pass\n",
        "def main():\n    ...\n",
        "def main():\n    \"\"\"doc only\"\"\"\n",
        "def main():\n    return 0\n",
        "\"\"\"def main(): in a docstring\"\"\"\n",
        "def main():\n    run()\n\nmain = None\n",
        "def main():\n    run()\n\nfrom x import main\n",
        "async def main():\n    await run()\n",
        "def main(:\n",
    )
    for source in bad:
        assert _entry_point_problem(source, "main") is not None, source
    assert _entry_point_problem("def main(argv=None):\n    \"\"\"doc\"\"\"\n    return run(argv)\n", "main") is None


def test_each_cli_entry_point_target_exists_and_defines_a_nontrivial_callable():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    files = []
    for name, target in scripts.items():
        module, func = target.split(":")
        rel = module.replace(".", "/") + ".py"
        assert (ROOT / rel).is_file(), f"{name}: {rel} missing"
        problem = _entry_point_problem((ROOT / rel).read_text(), func)
        assert problem is None, f"{name} -> {target}: {problem}"
        files.append(rel)
    assert sorted(PINS["entry_point_files"]) == sorted(files)


# ---- OpenCode: no python/js import and no dependency declaration (package.json, requirements*, pyproject, lock files) ----
_OPENCODE_PY = re.compile(r"^\s*(import|from)\s+opencode\b|ethen-code-oc|(__import__|import_module)\(\s*[\"\x27]opencode\b", re.M)  # statements only: upstream comments may mention OpenCode in prose
_OPENCODE_JS = re.compile(r"(?:\bfrom\s*|\brequire\(\s*|\bimport\(\s*|^\s*import\s+)[\"\x27]@?opencode[\w./-]*[\"\x27]|ethen-code-oc", re.M)
_OPENCODE_UVLOCK = re.compile(r"^\s*name\s*=\s*\"opencode([-_.][\w.-]*)?\"|ethen-code-oc", re.M | re.I)
_OC_PKG = re.compile(r"(?:^|/)opencode(?:[-_.]|/|$)")
_OC_REF = re.compile(r"ethen-code-oc|[/:]opencode(?:[-_.][\w.-]*)?(?:[#@?]|$)", re.I)
_NPM_SECTIONS = {"dependencies", "devDependencies", "peerDependencies", "optionalDependencies", "bundledDependencies", "bundleDependencies", "overrides", "resolutions", "packages"}
_PY_DEP_KEYS = {"dependencies", "optional-dependencies", "dependency-groups", "requires", "dev-dependencies", "override-dependencies", "constraint-dependencies", "sources"}


def _is_opencode_name(name) -> bool:
    n = str(name).strip().lower().lstrip("@").split("node_modules/")[-1]
    return bool(_OC_PKG.search(n))


def _opencode_in_package_json(text: str):
    if "ethen-code-oc" in text:
        return "ethen-code-oc"
    try:
        data = json.loads(text)
    except ValueError:  # JSONC or similar: textual fallback on quoted keys only
        m = re.search(r"\"(?:@[\w.-]+/)?opencode[\w./-]*\"\s*:", text)
        return m.group(0) if m else None

    def walk(node, in_dep):
        if isinstance(node, dict):
            for key, value in node.items():
                dep = in_dep or key in _NPM_SECTIONS
                if dep and _is_opencode_name(key):
                    return key
                hit = walk(value, dep)
                if hit:
                    return hit
        elif isinstance(node, list):
            for item in node:
                hit = walk(item, in_dep)
                if hit:
                    return hit
        elif isinstance(node, str) and in_dep and (_is_opencode_name(node) or _OC_REF.search(node)):
            return node
        return None

    return walk(data, False)


def _opencode_in_requirements(text: str):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue  # comments and prose never count
        line = re.sub(r"\s+#.*$", "", line)
        spec = re.sub(r"^(-e|--editable)\s+", "", line)
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec)
        egg = re.search(r"[#&]egg=([\w.-]+)", spec)
        if (m and _is_opencode_name(m.group(0))) or (egg and _is_opencode_name(egg.group(1))) or _OC_REF.search(spec):
            return raw
    return None


def _opencode_in_pyproject(text: str):
    if "ethen-code-oc" in text:
        return "ethen-code-oc"
    data = tomllib.loads(text)

    def walk(node, in_dep):
        if isinstance(node, dict):
            for key, value in node.items():
                dep = in_dep or key in _PY_DEP_KEYS
                if dep and _is_opencode_name(key):
                    return key
                hit = walk(value, dep)
                if hit:
                    return hit
        elif isinstance(node, list):
            for item in node:
                hit = walk(item, in_dep)
                if hit:
                    return hit
        elif isinstance(node, str) and in_dep and _opencode_in_requirements(node):
            return node
        return None

    return walk(data, False)


def test_opencode_scanners_flag_declarations_and_ignore_prose():
    flagged_npm = (
        "{\"dependencies\": {\"opencode-ai\": \"^1.0.0\"}}",
        "{\"devDependencies\": {\"@opencode-ai/sdk\": \"1\"}}",
        "{\"dependencies\": {\"opencode\": \"*\"}}",
        "{\"dependencies\": {\"x\": \"npm:opencode-ai@1\"}}",
        "{\"overrides\": {\"a\": {\"opencode_ai\": \"1\"}}}",
        "{\"packages\": {\"node_modules/opencode-ai\": {\"version\": \"1\"}}}",
        "{\"dependencies\": {\"x\": \"github:sst/opencode\"}}",
    )
    for text in flagged_npm:
        assert _opencode_in_package_json(text), text
    for text in (
        "{\"name\": \"x\", \"description\": \"notes on the archived opencode fork\", \"keywords\": [\"opencode\"], \"dependencies\": {\"react\": \"^18\"}}",
        "{\"scripts\": {\"build\": \"echo opencode is archived\"}}",
    ):
        assert not _opencode_in_package_json(text), text
    for text in ("opencode-ai==1.0\n", "OpenCode_AI>=1\n", "-e git+https://github.com/sst/opencode.git#egg=opencode\n", "ethen-code-oc @ git+https://example.invalid/x\n", "x==1\nopencode\n"):
        assert _opencode_in_requirements(text), text
    for text in ("# opencode is archived, never depend on it\nrequests==2\n", "requests==2  # not opencode\n", "opencodex==1\n"):
        assert not _opencode_in_requirements(text), text
    for text in ("[project]\ndependencies = [\"opencode-ai>=1\"]\n", "[project.optional-dependencies]\noc = [\"opencode\"]\n", "[tool.uv.sources]\nopencode-ai = { git = \"https://x/y\" }\n", "[dependency-groups]\ndev = [\"opencode-ai\"]\n"):
        assert _opencode_in_pyproject(text), text
    for text in ("[project]\nname = \"x\"\ndescription = \"mentions opencode in prose\"\nkeywords = [\"opencode\"]\ndependencies = [\"requests\"]\n",):
        assert not _opencode_in_pyproject(text), text
    assert _OPENCODE_PY.search("import opencode\n") and _OPENCODE_PY.search("x = __import__(\"opencode\")\n") and not _OPENCODE_PY.search("# import opencode in prose\n")
    assert _OPENCODE_JS.search("import x from \"opencode\"\n") and _OPENCODE_JS.search("const x = require(\"@opencode-ai/sdk\")\n") and not _OPENCODE_JS.search("// opencode is archived\n")


def test_no_python_or_dependency_file_imports_or_requires_opencode():
    here = Path(__file__).resolve()
    for rel in _repo_files():
        path = ROOT / rel
        name = path.name
        if path.resolve() == here or name == "UPSTREAM_PINS.json":
            continue
        if name in ("package.json", "package-lock.json", "npm-shrinkwrap.json"):
            hit = _opencode_in_package_json(path.read_text(errors="ignore"))
        elif name == "pyproject.toml":
            hit = _opencode_in_pyproject(path.read_text(errors="ignore"))
        elif re.fullmatch(r"(requirements|constraints)[^/]*\.(txt|in)", name):
            hit = _opencode_in_requirements(path.read_text(errors="ignore")) or _OPENCODE_PY.search(path.read_text(errors="ignore"))
        elif name == "uv.lock":
            hit = _OPENCODE_UVLOCK.search(path.read_text(errors="ignore"))
        elif path.suffix in (".py", ".toml", ".txt", ".cfg"):
            hit = _OPENCODE_PY.search(path.read_text(errors="ignore"))
        elif path.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            hit = _OPENCODE_JS.search(path.read_text(errors="ignore"))
        else:
            continue
        assert not hit, f"OpenCode reference in {rel}"


# ---- README wording: the recorded decision and the sandbox limits must stay stated ----
def test_readme_states_the_opencode_owner_decision_and_the_sandbox_limits():
    text = " ".join((ROOT / "ethen" / "code" / "README.md").read_text().split()).lower()
    for phrase in (
        "owner decision",
        "not pinned or re-verified",
        "private repository unreadable without credentials",
        "does not confine reads",
        "unix-socket ipc",
        "user d-bus",
        "rootless docker",
        "signals to same-uid host processes",
        "metadata changes",
        "uid 0 inside its user namespace",
        "namespaced capabilities",
        "network namespace alone",
        "non-upstream",
        "kernel 6.8",
        "landlock abi 4",
        "util-linux 2.39",
        "unsuitable for untrusted code",
        "ev6-045",
        "evidence/ev6-044-q3",
    ):
        assert phrase in text, phrase
    assert "kernel networking contains" not in text
    assert "both upstreams" not in text
