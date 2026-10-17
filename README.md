# py-repo-tools — Composer Package Finder (v2)

Streamlit app that pulls `composer.json` and `composer.lock` from the `master`, `main` and `develop` branches of every repo in a GitHub organisation (default `ramsalt`). You can then search for a package and see which repos use it and which version each branch has.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
cp .env.example .env          # then set GITHUB_TOKEN=... in .env (or paste into the sidebar)
.venv/bin/streamlit run app.py
```

Click **Fetch / refresh from GitHub** once. The results are cached in `.cache/<org>.json`, so searching works offline until you refresh again.

**Token:** a classic PAT needs the `repo` and `read:org` scopes. A fine-grained token needs Contents: Read-only on the org's repos. If the org uses SSO, authorise the token for SSO.

## Search

- Matches are substring and case-insensitive by default. Tick **Exact match** to require the full name (e.g. `drupal/core`).
- Branch columns show the locked version from `composer.lock`. `(not locked)` means the package is in `composer.json` but has no entry in the lock file.
- The **Constraint** column shows the version requirement from `composer.json`.

## Drupal security advisories (v2)

The **Drupal security advisories** tab pulls advisories from [drupal.org/security](https://www.drupal.org/security) (via the drupal.org `api-d7` JSON API) for a date you pick. You can also pick a date range. Dates use your local time.

Under each advisory it lists the Ramsalt repos that lock the affected package and their versions on `master` / `main` / `develop`:

- 🔴 the locked version is inside the advisory's affected range, so the branch needs updating
- 🟢 the locked version is outside the range
- ⚪ the version can't be determined (e.g. `dev-*` branches)

Drupal core advisories are matched against `drupal/core`. Contrib advisories are matched against `drupal/<project machine name>`. Advisory lists are cached for 1 hour and project names are cached in `.cache/drupal_projects.json`. Repo versions come from the last GitHub fetch, so refresh first if you need current versions.

### Renovate PRs

Each advisory row also shows the open Renovate PRs for that repo and package. The app finds them by searching open PRs authored by the Renovate bot user (sidebar setting, default `ramsalt-renovate-bot`) and reading the package table in each PR body.

- ✅ the PR updates to a version outside the affected range · ⚠️ the PR's target version is still affected · ❔ unknown · — no PR
- **Fix PR** is ticked only when a fixing PR targets a branch that is actually vulnerable. A PR to `master` doesn't count when only `develop` is affected.
- Core advisories also match PRs that update `drupal/core-recommended`.
- PRs are cached for 10 minutes. Click **Refresh Renovate PRs** to reload them.

## Tests

```bash
.venv/bin/python -m pytest -q
```
