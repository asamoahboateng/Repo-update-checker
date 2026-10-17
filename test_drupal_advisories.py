import pytest

from drupal_advisories import SAFE, UNKNOWN, VULNERABLE, check_version, packages_for_project

CORE = ">= 8.9.0 < 10.6.19 || >= 11.0.0 < 11.3.19 || >= 11.4.0 < 11.4.10 || >= 12.0.0-alpha1 < 12.0.0-beta2"


@pytest.mark.parametrize(
    "installed, affected, expected",
    [
        ("3.0.9", "<3.0.10", VULNERABLE),
        ("3.0.10", "<3.0.10", SAFE),
        ("4.1.3", "<4.1.4 || >=5.0.0 <5.0.16", VULNERABLE),
        ("4.1.4", "<4.1.4 || >=5.0.0 <5.0.16", SAFE),
        ("5.0.15", "<4.1.4 || >=5.0.0 <5.0.16", VULNERABLE),
        ("10.6.18", CORE, VULNERABLE),
        ("10.6.19", CORE, SAFE),
        ("11.4.9", CORE, VULNERABLE),
        ("11.3.20", CORE, SAFE),
        ("12.0.0-alpha3", CORE, VULNERABLE),
        ("12.0.0", CORE, SAFE),
        ("1.5", ">=1.0 <1.6", VULNERABLE),
        ("8.x-1.5", ">=1.0 <1.6", VULNERABLE),
        ("v2.0.0", "<2.0.1", VULNERABLE),
        ("1.0.0", "*", VULNERABLE),
        ("dev-1.x", "<2.0.0", UNKNOWN),
        ("2.x-dev", "<2.0.0", UNKNOWN),
        ("1.0.0", "", UNKNOWN),
    ],
)
def test_check_version(installed, affected, expected):
    assert check_version(installed, affected) == expected


def test_packages_for_project():
    assert packages_for_project("drupal") == ["drupal/core"]
    assert packages_for_project("webform") == ["drupal/webform"]
    assert packages_for_project("") == []


def test_parse_renovate_table_and_title():
    from renovate_prs import parse_updates

    body = (
        "| Package | Change | Release |\n|---|---|---|\n"
        "| [drupal/core-recommended](https://x) ([source](https://y)) | `10.6.18` → `10.6.19` | [10.6.19](z) |\n"
        "| drupal/core-dev | `11.4.8` -> `11.4.10` | |\n"
    )
    assert parse_updates("Update Drupal core", body) == {
        "drupal/core-recommended": {"from": "10.6.18", "to": "10.6.19"},
        "drupal/core-dev": {"from": "11.4.8", "to": "11.4.10"},
    }
    assert parse_updates("Update dependency drupal/gin to v5.0.16 (8.x)", "") == {
        "drupal/gin": {"from": "", "to": "5.0.16"}
    }


def test_core_alias_lookup():
    from renovate_prs import index_prs, prs_for

    pr = {"repo": "site-a", "updates": {"drupal/core-recommended": {"from": "1", "to": "2"}}}
    assert prs_for(index_prs([pr]), "site-a", "drupal/core") == [(pr, "drupal/core-recommended")]
    assert prs_for(index_prs([pr]), "site-b", "drupal/core") == []
