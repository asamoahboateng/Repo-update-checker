"""Streamlit UI: search composer packages across the Ramsalt GitHub org,
and match Drupal security advisories against them.

Run:  streamlit run app.py   (token read from .env → GITHUB_TOKEN)
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from composer_search import search
from drupal_advisories import SAFE, UNKNOWN, VULNERABLE, AdvisoryClient, check_version
from github_fetch import BRANCHES, GitHubClient, load_cache, save_cache
from renovate_prs import DEFAULT_AUTHOR, fetch_renovate_prs, index_prs, prs_for

load_dotenv(Path(__file__).parent / ".env")

DEFAULT_ORG = "ramsalt"
CACHE_DIR = Path(__file__).parent / ".cache"

st.set_page_config(page_title="Composer Package Finder", layout="wide")
st.title("Composer Package Finder")

with st.sidebar:
    st.header("Source")
    org = st.text_input("GitHub organisation", value=DEFAULT_ORG).strip()
    token = st.text_input(
        "GitHub token", value=os.environ.get("GITHUB_TOKEN", ""), type="password",
        help="Classic PAT with `repo` + `read:org`, or fine-grained with Contents: read on the org repos.",
    )
    include_archived = st.checkbox("Include archived repos", value=False)
    renovate_author = st.text_input("Renovate bot user", value=DEFAULT_AUTHOR).strip()
    refresh = st.button("Fetch / refresh from GitHub", type="primary", width="stretch")

cache_path = CACHE_DIR / f"{org.lower()}.json"

if refresh:
    if not token:
        st.sidebar.error("A GitHub token is required.")
    else:
        bar = st.progress(0.0, text="Starting…")

        def on_progress(done: int, total: int, name: str) -> None:
            bar.progress(min(done / max(total, 1), 1.0), text=f"{done}/{total} · {name}")

        try:
            data = GitHubClient(token).fetch_org(org, include_archived, on_progress)
        except Exception as exc:  # surface any API/auth error in the UI
            bar.empty()
            st.error(f"Fetch failed: {exc}")
        else:
            CACHE_DIR.mkdir(exist_ok=True)
            save_cache(data, cache_path)
            bar.empty()
            st.success(f"Fetched {len(data['repos'])} repos with composer files.")

data = load_cache(cache_path)
if data:
    st.caption(f"`{data['org']}` · {len(data['repos'])} repos with composer files · last fetched {data['fetched_at']} UTC")
else:
    st.warning("No repo data yet — click **Fetch / refresh from GitHub** in the sidebar to see which repos use each package.")
    data = {"org": org, "fetched_at": "", "repos": {}}

REPO_LINK = st.column_config.LinkColumn("Repo", display_text=r"https://github\.com/[^/]+/(.*)")
tab_search, tab_advisories = st.tabs(["Package search", "Drupal security advisories"])

with tab_search:
    col_term, col_exact = st.columns([4, 1])
    term = col_term.text_input("Package", placeholder="e.g. drupal/core or webform")
    exact = col_exact.checkbox("Exact match", value=False)

    if term:
        results = search(data, term, exact)
        if not results:
            st.warning("No repos contain a matching package.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "Repo": r["url"],
                        "Package": r["package"],
                        "composer.json": r["constraint"],
                        **{b: r["branches"].get(b, "") for b in BRANCHES},
                        "Dev": r["dev"],
                    }
                    for r in results
                ]
            )
            st.write(f"**{df['Repo'].nunique()}** repos · **{len(df)}** matches")
            st.dataframe(
                df,
                hide_index=True,
                width="stretch",
                column_config={
                    "Repo": REPO_LINK,
                    "composer.json": st.column_config.TextColumn("Constraint (composer.json)"),
                    "Dev": st.column_config.CheckboxColumn("Dev"),
                },
            )
            st.download_button("Download CSV", df.to_csv(index=False), file_name=f"{term}-usage.csv")


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_advisories(start: date, end: date, include_psa: bool) -> list[dict]:
    return AdvisoryClient(CACHE_DIR / "drupal_projects.json").advisories_between(start, end, include_psa)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_prs(org: str, author: str, token: str) -> list[dict]:
    return fetch_renovate_prs(GitHubClient(token), org, author)


STATUS_ICON = {VULNERABLE: "🔴", SAFE: "🟢", UNKNOWN: "⚪"}
FIX_ICON = {SAFE: "✅", VULNERABLE: "⚠️", UNKNOWN: "❔"}


def renovate_columns(repo: str, package: str, affected: str, pr_index: dict, vulnerable_branches: set[str]) -> dict:
    """Summarise open Renovate PRs for one repo/package against an advisory.

    "Fix PR" is only set when a PR moves a *vulnerable* branch to a version outside the affected range.
    """
    matches = prs_for(pr_index, repo, package)
    if not matches:
        return {"Renovate": "— no PR", "Renovate PR": None, "Fix PR": False}
    parts, fixing, seen = [], [], set()
    for pr, name in matches:
        if pr["url"] in seen:  # same PR matched via drupal/core and drupal/core-recommended
            continue
        seen.add(pr["url"])
        target = pr["updates"][name]["to"]
        status = check_version(target, affected)
        if status == SAFE and (pr["base"] in vulnerable_branches or not vulnerable_branches):
            fixing.append(pr)
        parts.append(f"{FIX_ICON[status]} {pr['base']} → {target}" + (" (draft)" if pr["draft"] else ""))
    best = (fixing or [matches[0][0]])[0]
    return {"Renovate": " · ".join(parts), "Renovate PR": best["url"], "Fix PR": bool(fixing)}


with tab_advisories:
    c_date, c_psa, c_only = st.columns([2, 1, 1])
    picked = c_date.date_input(
        "Advisory date (pick one day, or a range)", value=(date.today(), date.today()), max_value=date.today(),
        format="YYYY-MM-DD",
    )
    include_psa = c_psa.checkbox("Include PSAs", value=False)
    only_used = c_only.checkbox("Only advisories affecting our repos", value=False)

    if isinstance(picked, (tuple, list)):
        start, end = (picked[0], picked[-1]) if picked else (date.today(), date.today())
    else:
        start = end = picked

    pr_index: dict = {}
    if token:
        if st.button("Refresh Renovate PRs"):
            fetch_prs.clear()
        try:
            with st.spinner("Loading open Renovate PRs…"):
                pr_index = index_prs(fetch_prs(org, renovate_author, token))
        except Exception as exc:
            st.error(f"Could not load Renovate PRs: {exc}")
    else:
        st.caption("Add a GitHub token to see Renovate PRs.")

    try:
        with st.spinner("Loading advisories from drupal.org…"):
            advisories = fetch_advisories(start, end, include_psa)
    except Exception as exc:
        st.error(f"Could not load advisories: {exc}")
        advisories = []

    rendered = []
    for adv in advisories:
        rows = []
        for pkg in adv["packages"]:
            for r in search(data, pkg, exact=True):
                statuses = {b: check_version(v, adv["affected"]) for b, v in r["branches"].items()}
                rows.append(
                    {
                        "Repo": r["url"],
                        "Package": r["package"],
                        **{
                            b: f"{STATUS_ICON[statuses[b]]} {r['branches'][b]}" if b in r["branches"] else ""
                            for b in BRANCHES
                        },
                        "Vulnerable": any(s == VULNERABLE for s in statuses.values()),
                        **renovate_columns(
                            r["repo"], r["package"], adv["affected"], pr_index,
                            {b for b, st_ in statuses.items() if st_ == VULNERABLE},
                        ),
                    }
                )
        rendered.append((adv, rows))

    affecting = [x for x in rendered if x[1]]
    vulnerable = [x for x in affecting if any(r["Vulnerable"] for r in x[1])]
    label = start.isoformat() if start == end else f"{start.isoformat()} → {end.isoformat()}"
    vuln_rows = [r for _, rows in rendered for r in rows if r["Vulnerable"]]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Advisories ({label})", len(advisories))
    m2.metric("Used in our repos", len(affecting))
    m3.metric("With vulnerable branches", len(vulnerable))
    m4.metric("Vulnerable rows with a fix PR", f"{sum(r['Fix PR'] for r in vuln_rows)} / {len(vuln_rows)}")
    st.caption(
        "🔴 locked version is in the affected range · 🟢 not affected · ⚪ could not determine (dev branch / unparsable)  \n"
        "Renovate: ✅ PR updates to a fixed version · ⚠️ PR target is still affected · ❔ can't tell · — no PR. "
        "**Fix PR** is ticked only when a fixing PR targets a vulnerable branch."
    )

    if not advisories:
        st.info("No advisories published in this period.")

    for adv, rows in rendered:
        if only_used and not rows:
            continue
        with st.container(border=True):
            st.markdown(f"**[{adv['title']}]({adv['url']})**")
            meta = [adv["created"].strftime("%Y-%m-%d %H:%M"), f"project `{adv['project'] or '?'}`"]
            if adv["affected"]:
                meta.append(f"affected `{adv['affected']}`")
            if adv["cves"]:
                meta.append(", ".join(adv["cves"]))
            st.caption(" · ".join(meta))
            if not rows:
                st.write("Not used in any repo.")
                continue
            df = pd.DataFrame(rows).sort_values(["Vulnerable", "Repo"], ascending=[False, True])
            st.dataframe(
                df,
                hide_index=True,
                width="stretch",
                column_config={
                    "Repo": REPO_LINK,
                    "Vulnerable": st.column_config.CheckboxColumn("Vulnerable"),
                    "Fix PR": st.column_config.CheckboxColumn("Fix PR"),
                    "Renovate PR": st.column_config.LinkColumn("Renovate PR", display_text=r".*/pull/(\d+)$"),
                },
            )
