"""Alternatives in postings: which skill lists are a choice and which are separate asks."""

from __future__ import annotations

import pytest

from src.skill_groups import alternative_groups


def groups(text):
    return [(set(g.skills), g.reason) for g in alternative_groups(text)]


@pytest.mark.parametrize("text, want", [
    ("Proficiency in programming languages such as Python, R, or Java",
     [({"Python", "R", "Java"}, "or")]),
    ("Experience with Tableau, Power BI, or QuickSight", [({"Tableau", "Power BI", "Amazon QuickSight"}, "or")]),
    ("Coding skills in R and/or Python", [({"R", "Python"}, "or")]),
    ("Strong hands on proficiency with SQL and Python or R", [({"Python", "R"}, "or")]),
    ("Familiarity with popular frameworks (like TensorFlow, PyTorch, etc) is a plus",
     [({"TensorFlow/Keras", "PyTorch"}, "cue")]),
    ("cloud data warehouses such as Snowflake, BigQuery, Redshift, or similar platforms",
     [({"Snowflake", "BigQuery", "Redshift"}, "or")]),
    # A word the skills list doesn't know doesn't break the list.
    ("Use one or more visualization tools (e.g. Excel, Tableau, QuickSight, MicroStrategy, PowerBI)",
     [({"Excel", "Tableau", "Amazon QuickSight", "Power BI"}, "cue")]),
    ("2+ years of Tableau Desktop, Quicksight or other relevant software experience",
     [({"Tableau", "Amazon QuickSight"}, "or")]),
    ("Experience with data visualization using Tableau, Quicksight, or similar tools",
     [({"Tableau", "Amazon QuickSight"}, "or")]),
    ("Deep learning frameworks (e.g., PyTorch, TensorFlow) and/or distributed systems",
     [({"PyTorch", "TensorFlow/Keras"}, "cue")]),
])
def test_choices_are_found(text, want):
    assert groups(text) == want


@pytest.mark.parametrize("text", [
    "Proficiency in programming languages such as Python and SQL",  # both wanted
    "Experience with AWS services including S3, Redshift, and EC2",
    "Build AI/ML models with React/TypeScript and Go",  # a slash joins one compound skill
    "Strong software development experience using C/C++ and Python",
    "Use SQL daily. Python or R is a plus",  # no list crosses a sentence
    "Dashboards in Tableau, Power BI, and Looker, or other tools",  # "and" closes the list first
])
def test_separate_asks_are_left_alone(text):
    assert not [g for g in groups(text) if {"Python", "SQL"} <= g[0] or {"AWS", "Redshift"} <= g[0]
                or {"React", "TypeScript"} <= g[0] or {"C/C++", "Python"} <= g[0]]


def test_flattened_bullets_are_split():
    text = "Basic Qualifications - Experience with Python - Experience with Tableau or Power BI"
    assert groups(text) == [({"Tableau", "Power BI"}, "or")]
