"""Tests for the 2026-11-19 cleanup: subject aliases and the consent-page check."""
from types import SimpleNamespace

import crawler
from crawler import normalize_company_name, build_subject_index

# Two other test modules replace crawler.fetch_article_text at import time;
# keep the real one (this module is collected first).
_fetch_article_text = crawler.fetch_article_text


def test_alias_folds_mangled_subject():
    assert normalize_company_name("Beyond Privacy Coins Arcium") == "arcium"
    assert normalize_company_name("Alpha Compute Corp") == "alpha compute"


def test_alias_needs_whole_words():
    # 'arcium' inside a longer word is not the company
    assert normalize_company_name("Sparcium Labs") == "sparcium labs"


def test_custom_aliases_replace_defaults():
    assert normalize_company_name("Acme Widgets", aliases=("acme",)) == "acme"
    assert normalize_company_name("Arcium", aliases=()) == "arcium"


def test_build_subject_index_merges_aliases():
    dont = [{"title": "Acme Widgets launches X"}, {"title": "Acme ships Y"}]
    index = build_subject_index(dont, [], aliases=("acme",))
    assert list(index) == ["Acme"]
    assert len(index["Acme"]) == 2


def _fake_get(final_url):
    def get(url, **kw):
        return SimpleNamespace(url=final_url, raise_for_status=lambda: None,
                               content=b"<html><article><p>" + b"word " * 60 + b"</p></article></html>",
                               text="<html><article><p>" + "word " * 60 + "</p></article></html>",
                               encoding="utf-8", apparent_encoding="utf-8", headers={})
    return get


def test_consent_page_is_rejected(monkeypatch):
    monkeypatch.setattr(crawler.requests, "get", _fake_get("https://www.consent.google.com/x"))
    assert _fetch_article_text("https://example.com/a") == ""


def test_www_prefix_only_is_stripped(monkeypatch):
    # lstrip("www.") strips any leading w and '.', so wwwgoogle.com became
    # google.com and a real article there was thrown away as a consent page.
    monkeypatch.setattr(crawler.requests, "get", _fake_get("https://wwwgoogle.com/article"))
    assert "word" in _fetch_article_text("https://wwwgoogle.com/article")
