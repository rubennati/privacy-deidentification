"""The ML stack must be pinned to local-only (offline) resolution at runtime.

These guard the DSGVO offline guarantee: with the api/worker network isolated (no egress), the
libraries must not even *attempt* an outbound model/data lookup.
"""

from __future__ import annotations

import os

import pytest

from app.services import offline_ml_runtime


def test_hf_offline_env_defaults_to_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    offline_ml_runtime.configure_offline_ml_runtime()

    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_hf_offline_env_does_not_override_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")

    offline_ml_runtime.configure_offline_ml_runtime()

    # setdefault must not clobber an explicit operator choice.
    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_tldextract_default_extractor_has_no_remote_urls() -> None:
    tldextract = pytest.importorskip("tldextract")

    offline_ml_runtime.configure_offline_ml_runtime()

    # Presidio's EmailRecognizer calls the module-level tldextract.extract(), which delegates to
    # this default extractor; empty suffix_list_urls means snapshot-only, no runtime fetch.
    assert tuple(tldextract.TLD_EXTRACTOR.suffix_list_urls) == ()
    # And it still resolves domains from the bundled snapshot.
    assert tldextract.extract("office@example.at").suffix == "at"


def test_tldextract_remote_fetch_is_globally_disabled() -> None:
    # The bulletproof guard: any extractor's remote fetch is short-circuited to the snapshot,
    # regardless of its configured urls or import order — so no analysis can trigger a network call.
    pytest.importorskip("tldextract")
    from tldextract import suffix_list

    offline_ml_runtime.configure_offline_ml_runtime()

    with pytest.raises(suffix_list.SuffixListNotFound):
        # Non-empty urls would normally fetch; the patch raises before any network access.
        suffix_list.find_first_response(cache=None, urls=["https://example.com/list"])


def test_configure_is_idempotent_and_never_raises() -> None:
    offline_ml_runtime.configure_offline_ml_runtime()
    offline_ml_runtime.configure_offline_ml_runtime()
