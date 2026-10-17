"""Fetch composer.json / composer.lock from every repo in a GitHub organisation."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

GRAPHQL_URL = "https://api.github.com/graphql"
BRANCHES = ("master", "main", "develop")
FILES = ("composer.json", "composer.lock")
PAGE_SIZE = 5  # composer.lock files are big; keep GraphQL responses small


def _alias(branch: str, filename: str) -> str:
    return f"{branch}_{filename.replace('composer.', '')}"  # e.g. main_lock


def _build_query() -> str:
    blobs = "\n".join(
        f'{_alias(b, f)}: object(expression: "{b}:{f}") '
        "{ ... on Blob { text isTruncated } }"
        for b in BRANCHES
        for f in FILES
    )
    return f"""
    query($org: String!, $cursor: String, $pageSize: Int!) {{
      organization(login: $org) {{
        repositories(first: $pageSize, after: $cursor, orderBy: {{field: NAME, direction: ASC}}) {{
          pageInfo {{ hasNextPage endCursor }}
          totalCount
          nodes {{
            name
            isArchived
            url
            {blobs}
          }}
        }}
      }}
    }}
    """


class GitHubClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        )

    def graphql(self, query: str, variables: dict) -> dict:
        for attempt in range(4):
            resp = self.session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=60)
            if resp.status_code in (502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errors"):
                raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")
            return payload["data"]
        resp.raise_for_status()
        return {}

    def raw_file(self, org: str, repo: str, branch: str, path: str) -> str | None:
        """Used when GraphQL truncates a large blob."""
        url = f"https://api.github.com/repos/{org}/{repo}/contents/{path}"
        resp = self.session.get(
            url, params={"ref": branch}, headers={"Accept": "application/vnd.github.raw"}, timeout=60
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def fetch_org(
        self,
        org: str,
        include_archived: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        """Return {"org", "fetched_at", "repos": {repo: {"url", "branches": {branch: {file: parsed}}}}}."""
        query = _build_query()
        cursor = None
        repos: dict = {}
        done = 0
        while True:
            data = self.graphql(query, {"org": org, "cursor": cursor, "pageSize": PAGE_SIZE})
            org_data = data.get("organization")
            if org_data is None:
                raise RuntimeError(f"Organisation '{org}' not found or token lacks access.")
            page = org_data["repositories"]
            total = page["totalCount"]
            for node in page["nodes"]:
                done += 1
                if progress:
                    progress(done, total, node["name"])
                if node["isArchived"] and not include_archived:
                    continue
                branches: dict = {}
                for branch in BRANCHES:
                    files: dict = {}
                    for filename in FILES:
                        blob = node.get(_alias(branch, filename))
                        if not blob:
                            continue
                        text = blob.get("text")
                        if blob.get("isTruncated") or text is None:
                            text = self.raw_file(org, node["name"], branch, filename)
                        if text is None:
                            continue
                        try:
                            files[filename] = json.loads(text)
                        except json.JSONDecodeError:
                            files[filename] = {"_error": "invalid JSON"}
                    if files:
                        branches[branch] = files
                if branches:
                    repos[node["name"]] = {"url": node["url"], "branches": branches}
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        return {
            "org": org,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "repos": repos,
        }


def save_cache(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data))


def load_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
