#!/usr/bin/env python3
"""Fail if any installed backend package has a known advisory we haven't accepted.

Queries OSV directly rather than shelling out to pip-audit: pip-audit builds a
throwaway venv via ensurepip, which is fragile (it dies with SIGABRT on this
project's macOS toolchain), and this only needs one HTTP call.

    uv run python scripts/audit_dependencies.py

Accepted advisories live in ACCEPTED below, each with a reason. An advisory with
no fix available is not automatically acceptable — it needs a reachability
argument written down, or the dependency needs replacing.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/"

# advisory id (or alias) -> why we are shipping with it
ACCEPTED: dict[str, str] = {
    "CVE-2024-23342": (
        "ecdsa: Minerva timing attack. Upstream declined to fix (out of scope for a "
        "pure-Python implementation). Arrives via python-jose; unreachable here because "
        "app.core.security signs and verifies with HS256 (HMAC) only and passes an "
        "explicit algorithms= allowlist, so no ECDSA code path is exercised. Removing it "
        "for good means migrating off python-jose to PyJWT."
    ),
}


def installed_packages() -> list[dict[str, str]]:
    out = subprocess.run(
        ["uv", "pip", "list", "--format", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def aliases_for(vuln_id: str) -> set[str]:
    """querybatch returns bare ids; ACCEPTED is written in CVE terms."""
    try:
        with urllib.request.urlopen(OSV_VULN + vuln_id, timeout=30) as resp:
            data = json.load(resp)
    except Exception:
        return {vuln_id}
    return {vuln_id, *(data.get("aliases") or [])}


def main() -> int:
    packages = installed_packages()
    queries = [
        {"package": {"name": p["name"], "ecosystem": "PyPI"}, "version": p["version"]}
        for p in packages
    ]
    results = post(OSV_BATCH, {"queries": queries}).get("results", [])

    unaccepted: list[str] = []
    accepted_seen: set[str] = set()

    for pkg, result in zip(packages, results):
        for vuln in result.get("vulns") or []:
            ids = aliases_for(vuln["id"])
            hit = ids & ACCEPTED.keys()
            if hit:
                accepted_seen |= hit
                continue
            preferred = sorted(i for i in ids if i.startswith("CVE-")) or sorted(ids)
            unaccepted.append(f"{pkg['name']} {pkg['version']}: {preferred[0]}")

    for entry in sorted(accepted_seen):
        print(f"accepted: {entry} — {ACCEPTED[entry].splitlines()[0]}")

    if unaccepted:
        print(f"\n{len(unaccepted)} unaccepted advisories:", file=sys.stderr)
        for entry in sorted(set(unaccepted)):
            print(f"  {entry}", file=sys.stderr)
        print(
            "\nBump the package, or add the advisory to ACCEPTED in this script with a "
            "reachability argument.",
            file=sys.stderr,
        )
        return 1

    print(f"\nno unaccepted advisories across {len(packages)} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
