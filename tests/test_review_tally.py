import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import review_tally  # noqa: E402


def test_tally_adds_and_flags_areas_that_keep_coming_back(tmp_path):
    csv_path = tmp_path / "tally.csv"
    for run in ("2026-10-20_0900", "2026-10-21_0900", "2026-10-22_0900"):
        review_tally.add([{"area": "wording-match", "status": "fixed", "problem": "plural not matched"},
                          {"area": "nonsense", "status": "??", "problem": "odd"},
                          {"area": "letter", "status": "fixed", "problem": ""}], csv_path, run)
    text = review_tally.summary(csv_path)
    assert "| wording-match | 1 | 1 | 1 | 3 |" in text
    assert "| other | 1 | 1 | 1 | 3 |" in text  # unknown area kept as other; empty problem dropped
    assert "letter" not in text
    assert "3 or more of these runs (look for a source fix): other, wording-match" in text


def test_tally_without_reviews():
    assert review_tally.summary(Path("missing.csv")) == "No reviews tallied yet.\n"
