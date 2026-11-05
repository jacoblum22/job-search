"""Every past "same wording" bug, in one place: evidence, the check and the grade all
use src/tailor/wording.py, so each case holds for all of them."""

import pytest

from src.tailor import wording
from src.tailor.checks import _wording_in
from src.tailor.evidence import term_exact
from src.tailor.taxonomy import exact


@pytest.mark.parametrize("words, text", [
    ("data pipelines", "Skill: Data Pipeline Design"),      # plural vs singular
    ("dashboard", "Fixed three dashboards"),
    ("boxes", "Shipped one box a day"),
    ("APIs", "Called the API"),
    ("data-driven", "a data driven team"),                  # hyphen vs space
    ("e commerce", "e-commerce analytics"),
    ("data warehouse", "loaded the data warehouses"),
])
def test_variants_every_step_treats_as_the_same(words, text):
    assert wording.same(words, text) and wording.ats(words, text)
    assert _wording_in(words, text) and exact(words, text)
    assert term_exact({"term": words, "raw": [words]}, text)


@pytest.mark.parametrize("words, text", [
    ("data modeling", "data modelling in BigQuery"),
    ("visualisation", "data visualization"),
    ("behavioral data", "behavioural data"),
])
def test_spelling_counts_for_truth_checks_not_for_the_ats(words, text):
    assert wording.same(words, text) and _wording_in(words, text)
    assert not wording.ats(words, text) and not exact(words, text)


@pytest.mark.parametrize("words, text", [
    ("data warehous", "a warehouse of data"),   # a cut-off word is not a phrase
    ("data pipelines", "a pipeline of customer data"),
    ("R", "Rust and React"),                    # whole words only
    ("C", "C++ and C#"),
    ("Java", "JavaScript"),
    ("SQL", "NoSQL stores"),
])
def test_different_wording_never_matches(words, text):
    assert not wording.same(words, text) and not wording.ats(words, text)


def test_count_includes_plurals():
    assert wording.count("dashboard", "A dashboard, two dashboards, Dashboards.") == 3


@pytest.mark.parametrize("words, text", [
    ("KPIs", "Traced every metric back to source SQL."),
    ("key performance indicators", "Caught broken metrics in QA."),
    ("metrics", "Reported weekly KPIs."),
    ("data analytics", "Descriptive data analysis for the Loyalty team."),
])
def test_equivalent_wordings_back_each_other(words, text):
    # Jake, Oct 23 2026: wordings that name one thing are the same wording for the truth checks,
    # but the ATS still wants the posting's own word.
    assert wording.same(words, text) and _wording_in(words, text)
    assert term_exact({"term": words}, text)
    assert not wording.ats(words, text)


@pytest.mark.parametrize("words, text", [
    ("MS Office", "Kept the shift rota in Microsoft Office"),
    ("Microsoft Excel", "Built reports in MS Excel"),
    ("MS-Office", "Microsoft Office (Word, Excel)"),
])
def test_ms_is_microsoft_before_a_microsoft_product(words, text):
    # Amazon ICQA, Oct 27 2026: a product spelled out in the vault didn't back it abbreviated.
    assert wording.same(words, text) and _wording_in(words, text)
    assert not wording.ats(words, text)


def test_ms_alone_is_not_microsoft():
    assert not wording.same("Microsoft", "MS in Statistics")
    assert not wording.same("MS Office", "Microsoft Teams")


def test_vague_words_are_not_equivalents():
    assert not wording.same("insights", "data analysis") and not wording.same("analytics", "data analysis")


@pytest.mark.parametrize("words, text", [
    ("optimizing", "Optimized for 16GB VRAM with gradient checkpointing"),
    ("optimizing", "Whisper model size optimization"),
    ("optimising", "optimized the query"),
    ("automated", "monthly report automation"),
    ("data validation", "validated the data validating each field"),
])
def test_verb_forms_back_each_other_for_truth_checks_only(words, text):
    # Nexthop new grad, Oct 27 2026: "optimizing" found no passage though the vault says "Optimized".
    assert wording.same(words, text)
    assert not wording.ats(words, text)


@pytest.mark.parametrize("words, text", [
    ("marketing", "the market grew"),
    ("state", "stated plainly"),
    ("optimizing", "optimal settings"),
])
def test_verb_forms_stay_inside_their_family(words, text):
    assert not wording.same(words, text)
