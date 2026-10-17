"""Search cached composer data for a package across repos and branches."""

from __future__ import annotations


def _lock_packages(lock: dict) -> dict[str, tuple[str, str]]:
    """name -> (version, section) from composer.lock."""
    out: dict[str, tuple[str, str]] = {}
    for section in ("packages", "packages-dev"):
        for pkg in lock.get(section) or []:
            name = pkg.get("name")
            if name:
                out[name.lower()] = (pkg.get("version", ""), section)
    return out


def _json_constraints(composer_json: dict) -> dict[str, tuple[str, str]]:
    """name -> (constraint, section) from composer.json."""
    out: dict[str, tuple[str, str]] = {}
    for section in ("require", "require-dev"):
        for name, constraint in (composer_json.get(section) or {}).items():
            out[name.lower()] = (str(constraint), section)
    return out


def search(data: dict, term: str, exact: bool = False) -> list[dict]:
    """Return one row per (repo, package) match, with a column per branch.

    Matches packages present in either composer.lock or composer.json.
    `term` is case-insensitive; substring match unless `exact`.
    """
    term = term.strip().lower()
    if not term:
        return []

    rows: dict[tuple[str, str], dict] = {}
    for repo, info in data.get("repos", {}).items():
        for branch, files in info["branches"].items():
            locked = _lock_packages(files.get("composer.lock") or {})
            required = _json_constraints(files.get("composer.json") or {})
            for name in locked.keys() | required.keys():
                if (name != term) if exact else (term not in name):
                    continue
                row = rows.setdefault(
                    (repo, name),
                    {"repo": repo, "url": info["url"], "package": name, "constraint": "", "dev": False, "branches": {}},
                )
                if name in locked:
                    version, section = locked[name]
                    row["branches"][branch] = version
                    row["dev"] = row["dev"] or section == "packages-dev"
                else:
                    row["branches"][branch] = "(not locked)"
                if name in required:
                    constraint, section = required[name]
                    row["constraint"] = row["constraint"] or constraint
                    row["dev"] = row["dev"] or section == "require-dev"

    return sorted(rows.values(), key=lambda r: (r["package"], r["repo"]))
