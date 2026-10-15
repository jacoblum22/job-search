from src.db import Job, connect, upsert_job


def test_upsert_refreshes_longer_description(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    first = Job(
        source="adzuna",
        external_id="1",
        title="HR Intern",
        company="Co",
        location="Vancouver",
        description="short",
        url="https://a.example/1",
    )
    row_id, was_new = upsert_job(conn, first)
    assert was_new
    second = Job(
        source="adzuna",
        external_id="1",
        title="HR Intern (updated)",
        company="Co",
        location="Vancouver, BC",
        description="short" + " full posting text" * 20,
        url="https://a.example/1b",
    )
    row_id2, was_new2 = upsert_job(conn, second)
    assert row_id2 == row_id
    assert not was_new2
    stored = conn.execute("SELECT title, description, location FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert stored["title"] == "HR Intern (updated)"
    assert stored["description"].startswith("short full")
    assert stored["location"] == "Vancouver, BC"
    conn.close()
