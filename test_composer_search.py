from composer_search import search

DATA = {
    "repos": {
        "site-a": {
            "url": "https://github.com/ramsalt/site-a",
            "branches": {
                "master": {
                    "composer.json": {"require": {"drupal/core": "^10"}},
                    "composer.lock": {"packages": [{"name": "drupal/core", "version": "10.2.1"}]},
                },
                "develop": {
                    "composer.json": {"require": {"drupal/core": "^10"}, "require-dev": {"drupal/devel": "^5"}},
                    "composer.lock": {
                        "packages": [{"name": "drupal/core", "version": "10.3.0"}],
                        "packages-dev": [{"name": "drupal/devel", "version": "5.1.0"}],
                    },
                },
            },
        },
        "site-b": {
            "url": "https://github.com/ramsalt/site-b",
            "branches": {"main": {"composer.json": {"require": {"drupal/webform": "^6"}}}},
        },
    }
}


def test_versions_per_branch():
    [row] = search(DATA, "drupal/core", exact=True)
    assert row["repo"] == "site-a"
    assert row["branches"] == {"master": "10.2.1", "develop": "10.3.0"}
    assert row["constraint"] == "^10"
    assert row["dev"] is False


def test_substring_and_case_insensitive():
    names = {(r["repo"], r["package"]) for r in search(DATA, "DRUPAL")}
    assert names == {("site-a", "drupal/core"), ("site-a", "drupal/devel"), ("site-b", "drupal/webform")}


def test_dev_flag_and_unlocked():
    [devel] = search(DATA, "devel")
    assert devel["dev"] is True and devel["branches"] == {"develop": "5.1.0"}
    [webform] = search(DATA, "webform")
    assert webform["branches"] == {"main": "(not locked)"}


def test_empty_term():
    assert search(DATA, "  ") == []
