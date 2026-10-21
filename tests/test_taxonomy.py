"""Taxonomy false matches and the skills added from the A-tier audit (Oct 19 2026)."""

import pytest

from src.skill_groups import _is_tool
from src.tailor import taxonomy


@pytest.mark.parametrize("text, wrong", [
    ("MySQL, PostgreSQL, Oracle, or MS SQL", "Master's degree"),
    ("High proficiency in the MS Office suite", "Master's degree"),
    ("LEAN or Six Sigma certification", "Sigma"),
    ("Analyze churn across subscription cohorts", "survival analysis"),
    ("Query optimization in BigQuery", "optimization / OR"),
    ("Sigma-specific optimization of workbooks", "optimization / OR"),
    ("allocate the rest to a group RRSP", "APIs / REST"),
    ("Excel at communicating complex ideas", "Excel"),
    ("degree as a full-time professional (non-academic) experience in data engineering",
     "degree in engineering"),
    ("gather business requirements from stakeholders", "business acumen"),
    ("maintain data integrity", "integrity / trustworthiness"),
    # Daily review, Oct 19 2026.
    ("customer retention, subscriptions, billing, and customer cohorts", "Bachelor's degree"),
    ("Basic scripting (PowerShell, Perl, VBScript, SQL)", "Bachelor's degree"),
    ("contact center business process outsourcing", "process improvement"),
    ("defect analysis, remediation, and regression testing", "regression"),
    ("Run regression, acceptance, integration, exploratory, and edge case tests", "regression"),
    ("Kubernetes clusters and cloud infrastructure", "clustering/segmentation"),
    ("Clustered data processing (Hadoop, Spark, MapReduce, Hive)", "clustering/segmentation"),
    ("Experience with non-relational databases / data stores", "relational databases / database design"),
    ("multi-step planning and tool/function calling to backend services", "incident response / on-call"),
    ("RAG, and inference optimization", "optimization / OR"),
    ("Familiarity with log schemas such as ECS or OCSF", "Amazon ECS"),
    ("Experience with Power BI dashboards", "business intelligence"),
    ("Databricks AI/BI Dashboards", "business intelligence"),
    ("match the brand's Hex codes", "Hex"),
    ("only the tip of the iceberg", "Apache Iceberg"),
    ("The median salary for this role", "descriptive statistics / correlation"),
    ("fine-tune our processes", "fine-tuning (LoRA / PEFT)"),
    ("LoRa radios on field sensors", "fine-tuning (LoRA / PEFT)"),
    ("fine-tune your skills on the job", "fine-tuning (LoRA / PEFT)"),
    ("Samsara (NYSE: IOT) is the pioneer", "IoT / sensor data"),
    ("At Bloomberg, we build", "Bloomberg"),
    ("Create and populate data structures using one or more schema definition languages",
     "data structures / algorithms"),
    ("Experience with Azure DevOps pipelines", "DevOps"),
])
def test_false_matches_are_gone(text, wrong):
    assert wrong not in taxonomy.find(text)


@pytest.mark.parametrize("text, right", [
    ("BS or MS in Computer Science", "Master's degree"),
    ("Sigma Computing dashboards", "Sigma"),
    ("survival models for time-to-event data", "survival analysis"),
    ("linear and integer programming", "optimization / OR"),
    ("build REST APIs", "APIs / REST"),
    ("Advanced Excel skills. Excel at an advanced level", "Excel"),
    ("proficient in Excel", "Excel"),
    ("Bachelor's degree in Software Engineering", "degree in engineering"),
    ("degree in Business or Economics", "degree in economics/business"),
])
def test_real_matches_still_work(text, right):
    assert right in taxonomy.find(text)


@pytest.mark.parametrize("text, skill", [
    ("strong debugging and troubleshooting skills", "debugging / troubleshooting"),
    ("participate in code reviews", "code review"),
    ("data transformation and preparation", "data transformation / preparation"),
    ("multi-source e-commerce data", "data integration"),
    ("combining multiple sources for stakeholder requests", "data integration"),
    ("performance tuning of SQL queries", "query / performance tuning"),
    ("we worked on keeping SQL queries efficient", "query / performance tuning"),
    ("Transformed third-party data in BigQuery", "data transformation / preparation"),
    ("Openly sharing knowledge was part of the culture", "teaching / knowledge sharing"),
    ("SQL (CTEs, window functions, views)", "SQL window functions / CTEs"),
    ("maintain data lineage and the data catalog", "data lineage / catalog"),
    ("perform root cause analysis", "root cause analysis"),
    ("requirements gathering with stakeholders", "requirements gathering"),
    ("Dataflow and Pub/Sub on GCP", "Google Cloud Dataflow / Apache Beam"),
    ("Dataflow and Pub/Sub on GCP", "Google Cloud Pub/Sub"),
    ("healthcare systems, terminology and procedures", "healthcare knowledge"),
    ("supports data-driven decision-making", "data-driven decision-making"),
    ("take ownership of your work", "ownership / accountability"),
    ("a commitment to continuous improvement", "continuous improvement"),
    ("sound judgment", "judgment"),
    ("proactively flags issues", "proactive"),
    ("build relationships with internal and external partners", "relationship building"),
    ("knowledge sharing across the team", "teaching / knowledge sharing"),
    # Daily review, Oct 19 2026: real posting wording.
    ("Perform unit, integration, system, and regression testing", "testing (unit/automated)"),
    ("Run regression, acceptance, integration, exploratory, and edge case tests", "QA / UAT"),
    ("dimension reduction, clustering, classification, regression techniques", "clustering/segmentation"),
    ("Experience with relational databases such as PostgreSQL", "relational databases / database design"),
    ("participate in the on-call rotation", "incident response / on-call"),
    ("Bachelor's degree or BSc in Computer Science", "Bachelor's degree"),
    ("Strong Excel skills, including XLOOKUP/INDEX-MATCH", "Excel"),
    ("t-test, Chi-squared", "hypothesis testing / inference"),
    ("Strong foundation in statistics and probability theory", "statistics"),
    ("transformer-based models", "deep learning / neural nets"),
    ("tool calling", "AI agents / agentic AI / MCP"),
    ("model registries, experiment tracking", "MLOps"),
    ("Clustered data processing (Hadoop, Spark, MapReduce, Hive)", "Hadoop/Hive"),
    ("Redshift, S3, AWS Glue, EMR, Kinesis, FireHose, Lambda", "Amazon Kinesis"),
    ("BDD/TDD practices", "testing (unit/automated)"),
    ("Familiarity with PMBOK", "project management"),
    ("secrets management and safe API handling", "data privacy / security"),
    ("simulation, digital twins", "scenario analysis / simulation"),
    ("Proficiency in PHP", "PHP"),
    ("programming languages (Kdb+/Q, Python, R, Java, C#, Spark)", "kdb+/q"),
    ("using tools such as Hex or comparable business intelligence platforms", "Hex"),
    ("BigQuery, Mixpanel, Superset, Python, Prefect, and Statsig", "Statsig"),
    ("Build small- to mid-size business intelligence (BI) solutions", "business intelligence"),
    ("Experience with BI or visualization tools", "business intelligence"),
    ("3+ years of industry data analysis experience", "data analysis"),
    ("enable self-serve analytics", "self-serve analytics"),
    ("Claude, Cursor, Linear, Supabase, Slack", "Supabase"),
    ("Presto/Trino", "Presto/Trino"),
    ("Unity Catalog, and Delta Lake", "Delta Lake"),
    ("Unity Catalog, and Delta Lake", "Unity Catalog"),
    ("Apache Iceberg", "Apache Iceberg"),
    ("Snowflake Cortex Search", "Snowflake Cortex"),
    ("Cortex Analyst and Cortex Agents", "Snowflake Cortex"),
    ("dbt, Dataform, SQLMesh or similar", "Dataform"),
    ("dbt, Dataform, SQLMesh or similar", "SQLMesh"),
    ("automation tools such as VisualCron", "VisualCron"),
    ("DataRobot, Dataiku", "Dataiku"),
    ("Lambda, ECS, DynamoDB, Kinesis, SNS, SQS, EventBridge", "Amazon SQS / SNS"),
    ("Lambda, ECS, DynamoDB, Kinesis, SNS, SQS, EventBridge", "Amazon ECS"),
    ("Docker, Kubernetes, AWS ECS", "Amazon ECS"),
    ("monitoring and logging tools (e.g., Prometheus, Grafana, ELK Stack)", "Prometheus"),
    ("monitoring and logging tools (e.g., Prometheus, Grafana, ELK Stack)", "Grafana"),
    ("monitoring and logging tools (e.g., Prometheus, Grafana, ELK Stack)", "ELK Stack"),
    ("JMeter or k6", "JMeter / k6"),
    ("automated testing tools such as Jest or Vitest", "Jest / Vitest"),
    ("accessibility, security, and performance testing", "performance / load testing"),
    ("experience with threat modeling and penetration testing", "threat modeling / penetration testing"),
    ("DevOps and MLOps practices", "DevOps"),
    ("Cloudflare, serverless", "serverless"),
    ("IAM roles and permissions", "IAM (identity and access management)"),
    ("Experience with CUDA development", "GPU computing / CUDA"),
    ("mean, median, variance, standard deviation, correlation", "descriptive statistics / correlation"),
    ("Conduct trendline and correlation analyses", "descriptive statistics / correlation"),
    ("SQL queries, views, and stored procedures", "SQL stored procedures"),
    ("fluent in Object Oriented development", "object-oriented programming"),
    ("Strong foundation in database design, data structures, and algorithms", "data structures / algorithms"),
    ("3+ years of data engineering experience", "data engineering"),
    ("seeking an experienced and versatile Analytics Engineer", "analytics engineering"),
    ("Support data migration activities", "data migration"),
    ("data mapping, and data modelling", "data mapping"),
    ("multidimensional (OLAP) databases", "OLAP / cubes"),
    ("T-SQL and MDX queries", "OLAP / cubes"),
    ("big data analytics", "big data"),
    ("Familiarity with ontologies, knowledge graphs, data catalogs", "knowledge graphs / ontologies"),
    ("fine-tuning methodologies", "fine-tuning (LoRA / PEFT)"),
    ("techniques such as LoRA, QLoRA, PEFT", "fine-tuning (LoRA / PEFT)"),
    ("named entity recognition, entity linking, intent detection", "named entity recognition / entity resolution"),
    ("model distillation, quantization", "model serving / inference optimization"),
    ("embeddings and vector search", "search / information retrieval"),
    ("conversational analytics and data agent features", "text-to-SQL / conversational analytics"),
    ("Change Management & Adoption", "change management"),
    ("Market Research for Division Core Processes", "market research"),
    ("Robotic process automation", "robotic process automation (RPA)"),
    ("Coda, Power Platform, Power BI, or similar low-code platforms", "low-code / no-code"),
    ("Familiarity with Anaplan", "Anaplan"),
    ("Marketo, SOQL", "Marketo"),
    ("Experience with Agentforce / Salesforce AI solutions", "Agentforce"),
    ("third-party tools (Revolution, Bloomberg, eVestment)", "Bloomberg"),
    ("Experience with Eagle PACE and Bloomberg is desired", "Bloomberg"),
    ("performance, attribution, risk, exposure, modeling", "investment performance / attribution"),
    ("Basic accounting working knowledge", "accounting (GAAP / IFRS)"),
    ("GAAP accounting, revenue recognition", "accounting (GAAP / IFRS)"),
    # A vault line lists it: the check must see the skill there too, or it calls the draft's
    # "basic accounting" invented instead of asking for the vault's wording.
    ("Some knowledge of economics, accounting, and statistics from classes", "accounting (GAAP / IFRS)"),
    ("knowledge of payroll and accounting", "accounting (GAAP / IFRS)"),
    ("Risk and compliance focus, regulatory requirements", "risk management / regulatory compliance"),
    ("Background in biostatistics or epidemiology", "epidemiology / biostatistics"),
    ("industrial IoT, facilities, building systems", "IoT / sensor data"),
    ("sensor data ingestion and calibration", "IoT / sensor data"),
    ("Excellent interpersonal skills", "interpersonal skills"),
    ("CFA or FRM is an asset", "CFA / FRM / CIPM"),
    ("Business Analysis Body of Knowledge (BABOK)", "CBAP / IIBA"),
    ("Google Cloud Professional Data Engineer Certification", "cloud certification"),
    ("Microsoft Azure Data Engineer Associate", "cloud certification"),
])
def test_new_skills(text, skill):
    assert skill in taxonomy.find(text)


def test_new_concepts_are_not_tier_score_tools():
    # Practices and domain knowledge aren't tools a posting can list as alternatives.
    for name in ["debugging / troubleshooting", "code review", "requirements gathering",
                 "SQL window functions / CTEs", "healthcare knowledge", "data integration"]:
        assert not _is_tool(name), name
    for name in ["Playwright", "Google Cloud Storage", "Google Cloud Pub/Sub"]:
        assert _is_tool(name), name


def test_daily_review_concepts_and_products():
    for name in ["data analysis", "business intelligence", "data engineering", "object-oriented programming",
                 "DevOps", "change management", "low-code / no-code", "descriptive statistics / correlation",
                 "accounting (GAAP / IFRS)", "cloud certification"]:
        assert not _is_tool(name), name
    for name in ["PHP", "Grafana", "Delta Lake", "Snowflake Cortex", "Anaplan", "JMeter / k6", "Presto/Trino"]:
        assert _is_tool(name), name
        assert name in taxonomy.TOOL_TYPES, name
    for product, platform in [("Delta Lake", "Databricks"), ("Snowflake Cortex", "Snowflake"),
                              ("Amazon ECS", "AWS"), ("Agentforce", "Salesforce/CRM")]:
        assert taxonomy.RELATED[product] == platform
        assert taxonomy.category(platform), platform


def test_named_api_products_and_node_get_their_own_skills():
    from src.tailor import taxonomy as tx

    assert tx.canonical("LLM APIs") == "LLMs / generative AI"
    assert tx.canonical("API Gateway") == "AWS API Gateway"
    assert tx.canonical("Microsoft Graph API") == "Microsoft Graph API"
    assert tx.canonical("Azure OpenAI") == "Azure OpenAI"
    assert tx.canonical("REST APIs") == "APIs / REST"
    assert tx.canonical("Node.js") == "Node.js"
    # Front-end JavaScript doesn't show the Node.js runtime, but Node.js work is JavaScript.
    assert "Node.js" not in tx.find("Vanilla JavaScript dashboard frontend")
    assert "JavaScript" not in tx.find("REST APIs in Node.js")
    assert tx.RELATED["Node.js"] == "JavaScript"


def test_exact_matches_singular_and_plural_wording():
    from src.tailor import taxonomy as tx

    assert tx.exact("relational database", "Relational databases, SQL")
    assert tx.exact("relational databases", "designed a relational database")
    assert tx.exact("dashboard", "maintained dashboards")
    assert tx.exact("API", "built REST APIs")
    assert not tx.exact("SQL", "SQLite")
    assert "relational databases / database design" in tx.find("joined tables on primary and foreign keys")


def test_bare_ownership_is_the_soft_skill_but_home_ownership_isnt():
    from src.tailor import taxonomy as tx

    assert tx.canonical("Ownership") == "ownership / accountability"
    assert tx.canonical("high ownership of your work") == "ownership / accountability"
    assert tx.canonical("home ownership") is None
    assert tx.canonical("employee ownership plan") is None


def test_owasp_is_its_own_skill_not_data_privacy():
    from src.tailor import taxonomy as tx

    assert tx.canonical("OWASP Top 10") == "secure coding / OWASP"
    assert tx.canonical("secure coding practices") == "secure coding / OWASP"
    assert tx.canonical("data security") == "data privacy / security"
