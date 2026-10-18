import importlib.util
import sqlite3
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "skills_crosscheck", Path(__file__).resolve().parent.parent / "scripts" / "skills_crosscheck.py"
)
sc = importlib.util.module_from_spec(spec)
sys.modules["skills_crosscheck"] = sc
spec.loader.exec_module(sc)

PAD = " " + "filler text about the role and the team. " * 8


def make_db(tmp_path, rows):
    db = tmp_path / "jobs.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, description TEXT, tier TEXT)")
    con.executemany("INSERT INTO jobs (description, tier) VALUES (?, ?)", rows)
    con.commit()
    con.close()
    return db


def test_parse_onet_tab_and_hot():
    text = "O*NET-SOC Code\tExample\tCommodity Code\tHot Technology\n1\tAcme BI\t1\tY\n2\tAcme BI\t1\tN\n3\tGo\t1\tN\n"
    names = {n.name: n for n in sc.parse_onet(text)}
    assert names["Acme BI"].hot is True
    assert "Go" in names


def test_parse_esco_alt_labels():
    text = 'preferredLabel,altLabels\nuse data tools,"data tooling\nanalytics tools"\n'
    got = {n.name for n in sc.parse_esco(text)}
    assert got == {"use data tools", "data tooling", "analytics tools"}


def test_usable_skips_short_and_common():
    assert not sc.usable(sc.Name("Go", "onet"))
    assert not sc.usable(sc.Name("Excel", "onet"))
    assert sc.usable(sc.Name("Excel", "onet", hot=True))
    assert sc.usable(sc.Name("Zorbify", "onet"))


def test_phrase_match_is_whole_and_case_insensitive():
    rx = sc.phrase_regex("Zorb")
    assert rx.search("we use zorb daily")
    assert not rx.search("zorbify everything")
    assert not sc.phrase_regex("C").search("C++")


def test_crosscheck_threshold_a_tier_and_coverage(tmp_path):
    rows = [("We use Zorbify and SQL here." + PAD, "B")] * 3 + [("Plain job. Quuxlang is needed." + PAD, "A")]
    rows += [("Nothing relevant." + PAD, "B")] * 36
    postings = sc.load_postings(make_db(tmp_path, rows))
    assert len(postings) == 40
    names = [sc.Name("Zorbify", "onet"), sc.Name("Quuxlang", "onet"), sc.Name("SQL", "onet"), sc.Name("Nopeware", "esco")]
    got = {r.name: r for r in sc.crosscheck(names, postings)}
    assert set(got) == {"Zorbify", "Quuxlang"}  # SQL covered by taxonomy, Nopeware unmatched
    assert got["Zorbify"].postings == 3 and got["Zorbify"].share == 3 / 40
    assert got["Quuxlang"].a_tier == 1  # 2.5% but in an A-tier posting
    assert "Zorbify" in sc.render_table(list(got.values()), 40)


def test_below_threshold_not_reported(tmp_path):
    rows = [("Zorbify once." + PAD, "B")] + [("Nothing." + PAD, "B")] * 99
    postings = sc.load_postings(make_db(tmp_path, rows))
    assert sc.crosscheck([sc.Name("Zorbify", "onet")], postings) == []


def test_main_with_local_files(tmp_path, capsys):
    db = make_db(tmp_path, [("Zorbify rocks." + PAD, "A")])
    onet = tmp_path / "ts.txt"
    onet.write_text("Example\tHot Technology\nZorbify\tY\n", encoding="utf-8")
    assert sc.main(["--onet", str(onet), "--db", str(db)]) == 0
    assert "Zorbify" in capsys.readouterr().out
