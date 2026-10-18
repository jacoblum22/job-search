"""Alternatives in postings: which lists are a choice, and what the options are."""

from __future__ import annotations

import pytest

from src.skill_groups import alternative_groups
from src.tailor import taxonomy


def groups(text):
    return [(g.options, g.reason) for g in alternative_groups(text)]


@pytest.mark.parametrize("text, want", [
    ("Proficiency in programming languages such as Python, R, or Java", [(("Python", "R", "Java"), "or")]),
    # Every item is an option, whether or not the skills list knows it.
    ("proficiency in programming languages such as Stata, R, or Python, and a keen interest in a PhD",
     [(("Stata", "R", "Python"), "or")]),
    ("Knowledge of Power Platform, including Power Apps, Power Automate, Dataverse, or Power BI, is an asset",
     [(("Power Apps", "Power Automate", "Dataverse", "Power BI"), "or")]),
    ("Experience building or maintaining dashboards using tools such as Superset, Looker, Tableau, or Power BI",
     [(("Superset", "Looker", "Tableau", "Power BI"), "or")]),
    ("Use SQL daily. Python or R is a plus", [(("Python", "R"), "or")]),  # no list crosses a sentence
    ("Coding skills in R and/or Python", [(("R", "Python"), "or")]),
    ("Strong hands on proficiency with SQL and Python or R", [(("Python", "R"), "or")]),
    ("Experience with C# or Python for tools and testing", [(("C#", "Python"), "or")]),
    ("Familiarity with popular frameworks (like TensorFlow, PyTorch, etc) is a plus",
     [(("TensorFlow", "PyTorch"), "cue")]),
    ("cloud data warehouses such as Snowflake, BigQuery, Redshift, or similar platforms",
     [(("Snowflake", "BigQuery", "Redshift"), "or")]),
    ("Use one or more visualization tools (e.g. Excel, Tableau, QuickSight, MicroStrategy, PowerBI)",
     [(("Excel", "Tableau", "QuickSight", "MicroStrategy", "PowerBI"), "cue")]),
    ("2+ years of Tableau Desktop, Quicksight or other relevant software experience",
     [(("Tableau Desktop", "Quicksight"), "or")]),
    ("Deep learning frameworks (e.g., PyTorch, TensorFlow) and/or distributed systems",
     [(("PyTorch", "TensorFlow"), "cue")]),
    # A space or slash keeps one option together.
    ("Experience with React, TypeScript/JavaScript, or comparable frontend technologies",
     [(("React", "TypeScript/JavaScript"), "or")]),
    ("coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, or Python",
     [(("C", "C++", "C#", "Java", "JavaScript", "Python"), "or")]),
])
def test_choices_are_found(text, want):
    assert groups(text) == want


def test_open_end_is_recorded_not_an_option():
    (g,) = alternative_groups("Experience with data visualization using Tableau, Quicksight, or similar tools")
    assert g.options == ("Tableau", "Quicksight") and g.open_end


@pytest.mark.parametrize("text", [
    "Proficiency in programming languages such as Python and SQL",  # both wanted
    "Experience with AWS services including S3, Redshift, and EC2",
    "Build AI/ML models with React/TypeScript and Go",
    "Strong software development experience using C/C++ and Python",
    "Dashboards in Tableau, Power BI, and Looker, or other tools",  # "and" closes the list first
    "Exposure to LLM APIs or AI development",  # one tool option only
    # Subjects of study, not tools.
    "Master's or PhD in Data Science, Computer Science, Statistics, or a related quantitative field",
    "Master's degree or above in BI, finance, engineering, statistics, computer science, mathematics or equivalent",
])
def test_separate_asks_are_left_alone(text):
    assert groups(text) == []


def test_flattened_bullets_are_split():
    text = "Basic Qualifications - Experience with Python - Experience with Tableau or Power BI"
    assert groups(text) == [(("Tableau", "Power BI"), "or")]


def test_products_are_their_own_skills():
    assert taxonomy.find("SageMaker") == {"Amazon SageMaker"}  # not AWS in general
    assert taxonomy.find("AWS S3") == {"AWS", "AWS S3"}  # the vault's S3 work still shows AWS
    assert taxonomy.find("lambda functions in Python") == {"Python"}
    assert taxonomy.find("Looker Studio dashboards") == {"Looker Studio", "dashboards"}
    assert taxonomy.find("Looker") == {"Looker"}
    assert taxonomy.RELATED["Vertex AI"] == "GCP"
