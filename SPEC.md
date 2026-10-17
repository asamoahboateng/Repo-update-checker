# Composer Package Finder: specification

## Purpose

An internal tool that shows which Ramsalt sites use which Composer packages, at which versions. It also answers "does this new Drupal security advisory affect us, and is Renovate already fixing it?" across all ~320 repos in the `ramsalt` GitHub org.

## Feature 1: Collect data from the repos

- **What it reads:** for every repo in the org, `composer.json` and `composer.lock` on the `master`, `main` and `develop` branches.
- **How:** through the GitHub GraphQL API, 5 repos per request, with all 6 files (3 branches × 2 files) in one query. GitHub cuts off large `composer.lock` files, so when a file comes back truncated it's downloaded again in full through the REST contents API.
- **What's skipped:** archived repos (optional), and repos with no composer files on any of the three branches.
- **Storage:** the result is saved as one snapshot with the time it was fetched, about 85 MB of JSON today.
- **Refresh:** manual, with a progress bar. Searching only ever reads the saved snapshot.

## Feature 2: Package search

- **Input:** a package name. Matching is case-insensitive and finds partial names; an "exact match" option requires the full name.
- **Where it looks:** both the lock file (`packages` and `packages-dev`) and `composer.json` (`require` and `require-dev`).
- **Output:** one row per repo and package, with:
  - the locked version on each branch
  - the version requirement from `composer.json`
  - a dev-dependency flag
  - `(not locked)` when the package is required but missing from the lock file
- **Export:** the results can be downloaded as CSV.

## Feature 3: Drupal security advisories

- **Input:** a date or a date range, in local time. PSAs (public service announcements) are hidden unless you ask for them.
- **Where advisories come from:** the drupal.org JSON API at `https://www.drupal.org/api-d7/node.json?type=sa&sort=created&direction=DESC&limit=50&page=N`. The tool pages backwards and stops once it passes the start date.
  - **Fields used:** `title`, `url`, `created`, `field_project`, `field_affected_versions`, `field_sa_type`, `field_sa_cve`, `field_is_psa`.
  - **Risk level:** read from the title ("Critical", "Moderately critical", …).
- **Advisory → Composer package:**
  - `field_project` is a node ID. Fetching `/api-d7/node/{id}.json` gives `field_project_machine_name`, which is then cached.
  - The machine name `drupal` maps to `drupal/core`. Anything else maps to `drupal/<machine_name>`.
- **Vulnerability check:** the tool compares each repo's locked version on each branch against `field_affected_versions`. That field uses Composer-style ranges, e.g. `>= 10.3.0 < 10.6.19 || >= 11.0.0 < 11.4.10`, or `*` for every version.
  - **Range rules:** `||` separates alternatives, and the parts inside an alternative must all be true.
  - **Operators:** `< <= > >= = == !=`.
  - **Version clean-up:** leading `v` is removed. Old-style versions like `8.x-1.5` become `1.5`. Pre-releases count (`12.0.0-alpha1` is lower than `12.0.0`).
  - **Results:** 🔴 vulnerable, 🟢 safe, or ⚪ unknown. Unknown covers `dev-*` versions, `*-dev` versions and anything that can't be parsed.
- **Output:**
  - **Totals:** advisories in the period, how many touch our repos, how many have a vulnerable branch, and vulnerable rows that have a fix PR.
  - **Per advisory:** a card showing its date, project, affected range and CVEs, plus a table of repos with each branch's version and status. Vulnerable repos sort first.
  - **Filter:** a toggle that shows only advisories affecting our repos.
- **Note:** advisories come out in batches, usually on Wednesdays, so most single days return nothing.

## Feature 4: Renovate PR detection

- **How PRs are found:** a GitHub search for `org:ramsalt is:pr is:open author:ramsalt-renovate-bot`, paginated. The bot name is configurable. Ramsalt's Renovate runs as a regular user, not the `app/renovate` GitHub app.
- **Reading each PR:** the updates table in the PR description, rows like `` | [drupal/x](…) ([source](…)) | `1.0.0` → `1.0.1` | ``. Single-package PRs that have no table fall back to the title, `Update dependency X to vY`.
- **Matching:** PRs are matched to rows by repo and package. A core advisory also matches PRs that update `drupal/core-recommended`. Each PR is counted once.
- **Per row:**
  - each PR's target branch and new version, marked ✅ fixes / ⚠️ still vulnerable / ❔ unknown
  - a link to the PR
  - **Fix PR** is true only when a fixing PR targets a branch that is actually vulnerable. A PR to `master` doesn't count when only `develop` is affected.

## Configuration

- GitHub org (default `ramsalt`)
- GitHub token: a classic token with the `repo` and `read:org` scopes, or a fine-grained token with Contents read access
- Renovate bot username
- Whether to include archived repos

## Caching

| Data | How long |
|---|---|
| Repo snapshot | Until the next manual refresh |
| Advisory lists | 1 hour |
| Project machine names | Permanent |
| Renovate PRs | 10 minutes |

## Suggested mapping to a Drupal module (e.g. `ramsalt_composer_audit`)

| Python piece | Drupal equivalent |
|---|---|
| `github_fetch.py` | `GitHubClient` service using Guzzle (`http_client`). A `QueueWorker` processes one page of repos per item, so it survives timeouts. The queue is filled by cron or a Drush command (`drush rca:fetch`). |
| Snapshot JSON | A custom table or content entity, `repo_package` (repo, branch, package, locked_version, constraint, is_dev, fetched), so search becomes an indexed SQL query rather than scanning 85 MB of JSON. |
| `drupal_advisories.py` | `AdvisoryFetcher` service. Store advisories as a content entity, or use `cache.default` with a 1-hour max-age. Keep project machine names in the State or key-value store. |
| `check_version()` | Use `composer/semver` (`Semver::satisfies($version, $affected)`), which is already in every Drupal codebase. It handles these range formats natively, so the hand-written comparison isn't needed. |
| `renovate_prs.py` | `RenovatePrFetcher` service with the same regex parsing. Cache for 10 minutes. |
| Streamlit tabs | Two admin routes under `/admin/reports/composer-audit`: a search form (Form API) with a results table, and an advisories page with a date or range field and one details or card element per advisory. |
| Settings sidebar | A config form (`ramsalt_composer_audit.settings`) for org, bot username and archived toggle. Keep the token in the Key module or `settings.php`, never in exported config. |
| "Refresh" buttons | Batch API for a manual refresh with progress, plus a cron or Drush command for the regular refresh. |

**Ideas the Drupal version makes easy:**

- Run a daily cron check that emails or posts to Slack the new advisories that have vulnerable branches with no fix PR.
- Use Views on the `repo_package` entity for filtering and CSV export (with `views_data_export`).

## Test cases to port

The tests in `test_drupal_advisories.py` and `test_composer_search.py` cover the tricky cases. Port them as PHPUnit unit tests:

- **Version ranges:** ranges with several `||` alternatives, pre-releases, `8.x-1.5` versions, `*`, and dev versions.
- **Renovate PRs:** reading the updates table, including the `([source](…))` suffix, and falling back to the title.
- **Core PRs:** matching `drupal/core` advisories to `drupal/core-recommended` PRs.
- **Package search:** partial and exact matching, the dev flag, and `(not locked)`.
