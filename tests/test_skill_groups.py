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


@pytest.mark.parametrize("text, want, open_end", [
    # Examples after a cue stand for a kind of tool, even when the list closes with "and" (Jake's call).
    ("Experience in Statistical Analysis packages such as R, SAS and Matlab", ("R", "SAS", "Matlab"), False),
    ("Proficiency in programming languages such as Python and SQL", ("Python", "SQL"), False),
    ("Use AWS services including SageMaker, Lambda and other AI/ML services", ("SageMaker", "Lambda"), True),
    ("tools such as Airflow, dbt and Dagster, or similar", ("Airflow", "dbt", "Dagster"), True),
    ("BI tools such as Tableau, Looker", ("Tableau", "Looker"), False),
    # "etc" makes a list examples with no cue at all.
    ("3+ years of analyzing and interpreting data with Redshift, Oracle, NoSQL etc. experience",
     ("Redshift", "Oracle", "NoSQL"), True),
    ("Cloud platforms (AWS, Azure, GCP and so on)", ("AWS", "Azure", "GCP"), True),
])
def test_example_lists_are_choices(text, want, open_end):
    (g,) = alternative_groups(text)
    assert (g.options, g.open_end) == (want, open_end)


def test_open_end_is_recorded_not_an_option():
    (g,) = alternative_groups("Experience with data visualization using Tableau, Quicksight, or similar tools")
    assert g.options == ("Tableau", "Quicksight") and g.open_end


@pytest.mark.parametrize("text", [
    "Experience with AWS services including S3, Redshift, and EC2",  # "including ... and" lists parts, all wanted
    "Build and deploy APIs using a modern engineering stack, including Docker and Kubernetes",
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


def test_lead_ins_and_list_kind():
    (g,) = alternative_groups("projects involving Microsoft 365, SharePoint, Power Platform, or similar environments")
    assert g.options == ("Microsoft 365", "SharePoint", "Power Platform")
    (g,) = alternative_groups("use Microsoft Office at an advanced level (e.g. Outlook, Word, Proficient in Excel, PowerPoint)")
    assert g.options == ("Outlook", "Word", "Excel", "PowerPoint")
    (g,) = alternative_groups("Use one or more industry analytics visualization tools (e.g. Excel, Tableau, QuickSight)")
    assert g.category == "industry analytics visualization tools" and g.category_skills == ("data visualization",)


def test_vault_false_matches():
    assert taxonomy.find("Supervisor: Julia Rubin") == set()
    assert taxonomy.find("Python, R, or Julia") >= {"Julia"}
    assert "Looker" not in taxonomy.find("tracing ^skill-looker-studio")
    assert "ERP (SAP/Oracle/Workday)" not in taxonomy.find("WiDS × SAP Customer Churn Prediction")
    assert "ERP (SAP/Oracle/Workday)" not in taxonomy.find("predict churn from SAP customer data. The WiDS x SAP competition")
    assert "ERP (SAP/Oracle/Workday)" in taxonomy.find("Oracle, SAP, or similar systems")


def test_list_type_comes_from_its_tools():
    (g,) = alternative_groups("Experience with data visualization using Tableau, Quicksight, or similar tools")
    assert g.tool_type == "BI / visualization tool"
    (g,) = alternative_groups("Experience with Pandas, PySpark, or AWS")  # mixed: no single type
    assert g.tool_type is None
    assert "BI / visualization tool" not in taxonomy.TOOL_TYPES["Excel"]  # Jake's call


def test_office_apps_and_ai_tools():
    assert taxonomy.find("Microsoft Office (Outlook, Word, Excel, PowerPoint)") >= {
        "Microsoft Outlook", "Microsoft Word", "Excel", "Microsoft PowerPoint"}
    assert taxonomy.find("a word of advice; the outlook is good") == set()
    assert taxonomy.find("GitHub Copilot, Cursor, or Claude Code") == {"GitHub Copilot", "Cursor", "Claude / Claude Code"}
    assert taxonomy.find("Spring 2026 term") == set()


def test_databases():
    assert taxonomy.find("PostgreSQL, MySQL or SQLite") == {"SQL"}  # SQL carries over
    assert taxonomy.find("MongoDB or DynamoDB") == {"MongoDB", "DynamoDB"}  # each NoSQL store is its own
    assert taxonomy.RELATED["Redis"] == "NoSQL"
