"""Fetch Drupal security advisories (drupal.org/security) and check versions against them."""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, time as dtime
from pathlib import Path

import requests
from packaging.version import InvalidVersion, Version

API = "https://www.drupal.org/api-d7"
PAGE_SIZE = 50
HEADERS = {"User-Agent": "ramsalt-py-repo-tools/2 (composer advisory checker)"}

# drupal.org project machine name -> composer packages to look for.
CORE_PACKAGES = ["drupal/core"]

VULNERABLE, SAFE, UNKNOWN = "vulnerable", "safe", "unknown"


# --------------------------------------------------------------------------- fetching

class AdvisoryClient:
    def __init__(self, project_cache_path: Path | None = None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.project_cache_path = project_cache_path
        self.projects: dict[str, str] = {}
        if project_cache_path and project_cache_path.exists():
            try:
                self.projects = json.loads(project_cache_path.read_text())
            except json.JSONDecodeError:
                self.projects = {}

    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def project_machine_name(self, project_id: str) -> str:
        if project_id not in self.projects:
            node = self._get(f"{API}/node/{project_id}.json")
            self.projects[project_id] = node.get("field_project_machine_name") or ""
            if self.project_cache_path:
                self.project_cache_path.parent.mkdir(exist_ok=True)
                self.project_cache_path.write_text(json.dumps(self.projects))
        return self.projects[project_id]

    def advisories_between(self, start: date, end: date, include_psa: bool = False) -> list[dict]:
        """Advisories created between start and end (inclusive, local time), newest first."""
        start_ts = datetime.combine(start, dtime.min).timestamp()
        end_ts = datetime.combine(end, dtime.max).timestamp()
        out: list[dict] = []
        page = 0
        while True:
            data = self._get(
                f"{API}/node.json",
                {"type": "sa", "sort": "created", "direction": "DESC", "limit": PAGE_SIZE, "page": page},
            )
            items = data.get("list") or []
            for item in items:
                created = int(item["created"])
                if created > end_ts:
                    continue
                if created < start_ts:
                    return out
                if item.get("field_is_psa") == "1" and not include_psa:
                    continue
                out.append(self._normalise(item))
            if not items or "next" not in data:
                return out
            page += 1

    def _normalise(self, item: dict) -> dict:
        project = item.get("field_project") or {}
        machine = self.project_machine_name(project["id"]) if project.get("id") else ""
        return {
            "id": item["nid"],
            "title": html.unescape(re.sub(r"\s+", " ", item["title"])).strip(),
            "url": item["url"],
            "created": datetime.fromtimestamp(int(item["created"])),
            "project": machine,
            "packages": packages_for_project(machine),
            "affected": item.get("field_affected_versions") or "",
            "type": item.get("field_sa_type") or "",
            "risk": _risk_from_title(item["title"]),
            "cves": item.get("field_sa_cve") or [],
            "is_psa": item.get("field_is_psa") == "1",
        }


def packages_for_project(machine_name: str) -> list[str]:
    if not machine_name:
        return []
    if machine_name == "drupal":
        return CORE_PACKAGES
    return [f"drupal/{machine_name}"]


def _risk_from_title(title: str) -> str:
    m = re.search(r"\b(Highly critical|Critical|Moderately critical|Less critical|Not critical)\b", title)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- version matching

_CONSTRAINT = re.compile(r"(>=|<=|!=|==|=|<|>)\s*([^\s|,]+)")


def _parse_version(raw: str) -> Version | None:
    v = raw.strip().lstrip("vV")
    m = re.match(r"^\d+\.x-(.+)$", v)  # legacy Drupal "8.x-1.5" -> "1.5"
    if m:
        v = m.group(1)
    if v.startswith("dev-") or v.endswith("-dev") or v.endswith(".x"):
        return None
    try:
        return Version(v)
    except InvalidVersion:
        return None


def _satisfies(version: Version, op: str, bound: Version) -> bool:
    return {
        "<": version < bound,
        "<=": version <= bound,
        ">": version > bound,
        ">=": version >= bound,
        "=": version == bound,
        "==": version == bound,
        "!=": version != bound,
    }[op]


def check_version(installed: str, affected: str) -> str:
    """Return VULNERABLE / SAFE / UNKNOWN for an installed version vs an affected-versions string."""
    affected = (affected or "").strip()
    version = _parse_version(installed or "")
    if not affected or version is None:
        return UNKNOWN
    for group in affected.split("||"):
        group = group.strip()
        if group == "*":
            return VULNERABLE
        parts = _CONSTRAINT.findall(group)
        if not parts:
            return UNKNOWN
        bounds = [(op, _parse_version(b)) for op, b in parts]
        if any(b is None for _, b in bounds):
            return UNKNOWN
        if all(_satisfies(version, op, b) for op, b in bounds):
            return VULNERABLE
    return SAFE
