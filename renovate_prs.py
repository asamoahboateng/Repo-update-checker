"""Find open Renovate PRs across the org and the package updates each one carries."""

from __future__ import annotations

import re

from github_fetch import GitHubClient

DEFAULT_AUTHOR = "ramsalt-renovate-bot"

_SEARCH = """
query($q: String!, $cursor: String) {
  search(query: $q, type: ISSUE, first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        title url number isDraft baseRefName headRefName
        repository { name }
        body
      }
    }
  }
}
"""

# A row of Renovate's "This PR contains the following updates" table:
# | [drupal/core](https://...) ([source](...)) | `10.6.18` → `10.6.19` | ...
_ROW = re.compile(
    r"^\|\s*(?:\[(?P<link>[^\]]+)\]\([^)]*\)|(?P<plain>[^|\s]+))[^|]*\|.*?`(?P<old>[^`]+)`\s*(?:→|->)\s*`(?P<new>[^`]+)`",
    re.MULTILINE,
)
# Fallback for "Update dependency drupal/fontyourface to v4.3.1 (8.x)"
_TITLE = re.compile(r"[Uu]pdate dependency (?P<pkg>\S+) to v?(?P<new>[^\s(]+)")


def parse_updates(title: str, body: str) -> dict[str, dict]:
    """package (lowercase) -> {"from": old or "", "to": new}."""
    updates: dict[str, dict] = {}
    for m in _ROW.finditer(body or ""):
        name = (m.group("link") or m.group("plain")).strip().lower()
        updates[name] = {"from": m.group("old").lstrip("v"), "to": m.group("new").lstrip("v")}
    if not updates:
        m = _TITLE.search(title or "")
        if m:
            updates[m.group("pkg").lower()] = {"from": "", "to": m.group("new").lstrip("v")}
    return updates


def fetch_renovate_prs(client: GitHubClient, org: str, author: str = DEFAULT_AUTHOR) -> list[dict]:
    """All open PRs by `author` in `org`, with parsed package updates."""
    query = f"org:{org} is:pr is:open author:{author}"
    prs: list[dict] = []
    cursor = None
    while True:
        data = client.graphql(_SEARCH, {"q": query, "cursor": cursor})["search"]
        for node in data["nodes"]:
            if not node:
                continue
            prs.append(
                {
                    "repo": node["repository"]["name"],
                    "base": node["baseRefName"],
                    "url": node["url"],
                    "number": node["number"],
                    "title": node["title"],
                    "draft": node["isDraft"],
                    "updates": parse_updates(node["title"], node["body"]),
                }
            )
        if not data["pageInfo"]["hasNextPage"]:
            return prs
        cursor = data["pageInfo"]["endCursor"]


# Renovate bumps the direct dependency, which may differ from the package an advisory names.
PACKAGE_ALIASES = {"drupal/core": ["drupal/core", "drupal/core-recommended"]}


def prs_for(index: dict[tuple[str, str], list[dict]], repo: str, package: str) -> list[tuple[dict, str]]:
    """Open PRs in `repo` updating `package` (or an alias), as (pr, matched package) pairs."""
    found: list[tuple[dict, str]] = []
    for name in PACKAGE_ALIASES.get(package, [package]):
        found += [(pr, name) for pr in index.get((repo, name), [])]
    return found


def index_prs(prs: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """(repo, package) -> PRs touching that package, for quick lookup."""
    index: dict[tuple[str, str], list[dict]] = {}
    for pr in prs:
        for pkg in pr["updates"]:
            index.setdefault((pr["repo"], pkg), []).append(pr)
    return index
