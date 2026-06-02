"""Spec discovery for `agentforce-probe scan`.

Walks a codebase and finds Agentforce test specs so a developer (or a Claude
Code session) can point the tool at a repo root and get "here are the N specs I
found, here's how to run each". Pure filesystem + YAML sniffing; no org/LLM call.

A file is treated as a candidate spec if:
  - its name matches a spec-like pattern (``*spec*.yaml`` / ``*spec*.yml`` /
    a file inside an ``agent-specs``/``agentforce``/``specs`` directory), AND
  - it parses as a YAML mapping that contains a ``testCases`` list.

We deliberately keep discovery cheap and side-effect free: directories commonly
excluded from source scans (``.git``, ``node_modules``, ``.venv`` …) are skipped.
"""

import os

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is a hard runtime dependency
    yaml = None

# Directories never worth descending into.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

SPEC_DIR_HINTS = {"agent-specs", "agentforce", "specs", "agent-tests", "agentforce-specs"}


def _name_looks_like_spec(filename):
    low = filename.lower()
    if not (low.endswith(".yaml") or low.endswith(".yml")):
        return False
    return "spec" in low


def _in_spec_dir(dirpath):
    parts = {p.lower() for p in dirpath.replace("\\", "/").split("/")}
    return bool(parts & SPEC_DIR_HINTS)


def _is_spec_content(path):
    """Return the parsed spec dict if the file is a valid Agentforce spec, else None."""
    if yaml is None:  # pragma: no cover
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            obj = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(obj, dict):
        return None
    cases = obj.get("testCases")
    if not isinstance(cases, list) or not cases:
        return None
    return obj


def discover_specs(root="."):
    """Walk `root` and return a sorted list of discovered spec descriptors.

    Each descriptor is a dict: {path, agent, num_cases, has_internal_signals}.
    `agent` is the spec's subjectName (or None). `has_internal_signals` is True
    when any case declares expectedTopic/expectedActions (richer scoring).
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        in_hint_dir = _in_spec_dir(dirpath)
        for fn in filenames:
            if not (fn.lower().endswith((".yaml", ".yml"))):
                continue
            if not (_name_looks_like_spec(fn) or in_hint_dir):
                continue
            full = os.path.join(dirpath, fn)
            spec = _is_spec_content(full)
            if spec is None:
                continue
            cases = spec.get("testCases", [])
            has_signals = any(("expectedTopic" in c or "expectedActions" in c) for c in cases if isinstance(c, dict))
            found.append(
                {
                    "path": os.path.normpath(full),
                    "agent": spec.get("subjectName"),
                    "num_cases": len(cases),
                    "has_internal_signals": has_signals,
                }
            )
    found.sort(key=lambda d: d["path"])
    return found


def render_discovery(specs, root="."):
    """Render a discovery report + suggested run commands."""
    lines = [f"Scanned {os.path.normpath(root)} — found {len(specs)} spec(s)."]
    if not specs:
        lines.append("")
        lines.append("No Agentforce specs found. A spec is a YAML file with a `testCases:` list,")
        lines.append("typically named `*-spec.yaml` or placed under an `agent-specs/` directory.")
        return "\n".join(lines)
    lines.append("")
    for s in specs:
        agent = s["agent"] or "(subjectName not set)"
        sig = "topic/actions" if s["has_internal_signals"] else "output-only"
        lines.append(f"  • {s['path']}")
        lines.append(f"      agent: {agent}  ·  {s['num_cases']} case(s)  ·  {sig}")
    lines.append("")
    lines.append("Run one with:")
    example = specs[0]
    agent_flag = f" --agent {example['agent']}" if example["agent"] else ""
    lines.append(f"  agentforce-probe run --org <alias>{agent_flag} --spec {example['path']}")
    return "\n".join(lines)
