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
    # Daily review, Oct 20 2026.
    ("Familiarity with marketing funnel metrics (MQLs, opportunities, pipeline)",
     "product analytics (funnels / cohorts / LTV)"),
    ("Strong SQLs and Python", "demand generation / lead funnel (MQLs)"),
    ("generate demand for our products", "demand generation / lead funnel (MQLs)"),
    # Daily review, Oct 29 2026.
    ("statistical modeling, econometrics, or control theory", "KPIs/metrics"),
    ("metadata management, data classification, and lineage tracking", "classification"),
    ("the highest probability of reaching $1 billion in annual revenue", "statistics"),
    ("connects brand and performance marketing to drive measurable results", "marketing analytics / attribution"),
    ("the systems that drive the user journey through purchasing", "product analytics (funnels / cohorts / LTV)"),
    ("join our Data Science team", "data science"),
    ("software supply chain security", "supply chain / inventory"),
    ("an enterprise service bus", "Azure integration services (Logic Apps / Service Bus / Event Grid)"),
    ("help bring new bank partners and payment rails to life", "Ruby on Rails"),
    ("Life at Unity", "Unity / Unreal Engine"),
    ("Unity Catalog, and Delta Lake", "Unity / Unreal Engine"),
    ("stack shipping containers", "Docker"),
    ("Management & Telemetry Protocols", "event tracking / instrumentation"),
    ("retail partnerships", "e-commerce / retail"),
    ("matches the Contoso Retail analytics work", "e-commerce / retail"),
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
    ("Data QA and integration of third-party e-commerce/marketing sources", "data integration"),
    ("integrated external vendor data feeds", "data integration"),
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
    # Daily review, Oct 20 2026: real posting wording.
    ("Familiarity with Acumatica customization is considered an asset", "Acumatica"),
    ("Experience working in an ERP system, particularly Acumatica or Sage Intacct", "Acumatica"),
    ("Hands-on exposure to Salesforce (SOQL, reports, campaign objects, admin concepts)", "SOQL"),
    ("Familiarity with marketing funnel metrics (MQLs, opportunities, pipeline) or B2B demand generation",
     "demand generation / lead funnel (MQLs)"),
    ("partners closely with Marketing Analytics, Demand Generation, and Marketing Operations",
     "demand generation / lead funnel (MQLs)"),
    ("with a strong bias toward automating repetitive work", "report / process automation"),
    ("Identify opportunities to automate repetitive reporting", "report / process automation"),
    ("automate manual processes where possible", "report / process automation"),
    ("conversion funnels and cohort retention", "product analytics (funnels / cohorts / LTV)"),
    # Daily review, Oct 29 2026: real posting wording.
    ("a strong foundation in data science, analytics, and applied machine learning", "data science"),
    ("Write clean, maintainable code following best practices and design patterns",
     "software architecture / system design"),
    ("Microservices and event-driven architectures", "event-driven architecture"),
    ("Site Reliability Engineering (SRE)", "site reliability engineering (SRE)"),
    ("Reliability engineering or SRE experience", "site reliability engineering (SRE)"),
    ("Contributing to open-source projects", "open-source contribution"),
    ("Use AI coding assistants and coding agents to accelerate development", "AI-assisted coding"),
    ("Actively uses AI development tools (code copilots, AI debuggers, test generators)", "AI-assisted coding"),
    ("The role analyzes product usage and telemetry", "event tracking / instrumentation"),
    ("define questions, success metrics, and measurement plans", "event tracking / instrumentation"),
    ("Directory Tables, Scoped URLs, Snowpark", "Snowpark"),
    ("Azure Integration Services (Logic Apps, API Management, Service Bus & Event Grid)",
     "Azure integration services (Logic Apps / Service Bus / Event Grid)"),
    ("statistical modeling, econometrics, or control theory", "econometrics"),
    ("statistical modeling, econometrics, or control theory", "control theory"),
    ("Familiarity with ads systems, auction theory, or related marketplace optimization problems",
     "ad tech / programmatic advertising"),
    ("SQL and ORM technologies (JPA2, Hibernate)", "ORM (Hibernate / SQLAlchemy)"),
    ("Worked on multithreaded applications", "concurrency / multithreading"),
    ("maintaining cryptographic systems and practices", "cryptography"),
    ("Experience building and maintaining production Ruby on Rails applications", "Ruby on Rails"),
    ("Three.js, WebGL, Babylon.js, Unity, or Unreal Engine", "Three.js / WebGL"),
    ("Three.js, WebGL, Babylon.js, Unity, or Unreal Engine", "Unity / Unreal Engine"),
    ("within a supply chain, retail, or consumer goods environment", "supply chain / inventory"),
    ("within a supply chain, retail, or consumer goods environment", "e-commerce / retail"),
    ("Experience in e-commerce, online marketplaces, or other platform-based businesses", "e-commerce / retail"),
    ("building and evaluating ... systems to detect harmful content and automate moderation workflows",
     "trust & safety / content moderation"),
    ("Experience in financial services, fraud detection, risk analytics", "fraud / risk analytics"),
    ("combining business context, systems thinking, and AI-native execution", "systems thinking"),
    ("Product-minded. You think beyond code", "product mindset"),
    # Fixes to existing entries.
    ("Azure Data Lake, Azure Synapse, and Data Bricks", "Databricks"),
    ("Familiarity with cloud platforms, containers, CI/CD pipelines", "Docker"),
    ("Familiarity with source control systems such as Git", "Git"),
    ("Experience with test-driven development is a plus", "testing (unit/automated)"),
    ("optimization, probability, statistical modeling", "statistics"),
    ("Experience in object detection, recognition, and tracking", "computer vision"),
    ("offline evaluations, online experiments, and production monitoring", "model evaluation/validation"),
    ("offline evaluations, online experiments, and production monitoring", "A/B testing / experimentation"),
    ("A/B testing, including sample size estimation", "A/B testing / experimentation"),
    ("anomaly detection, trend analysis, marketing mix modeling", "descriptive statistics / correlation"),
    ("Customer Acquisition Cost (CAC), Return on Ad Spend (ROAS)", "marketing analytics / attribution"),
    ("Partner with performance marketing teams", "marketing analytics / attribution"),
    ("Analyze conversion funnels and user journeys", "product analytics (funnels / cohorts / LTV)"),
    ("Develop prompts, tools, workflows, and evaluation harnesses", "LLM / AI evaluation"),
    ("alignment with defined acceptance criteria", "requirements gathering"),
    ("workflow orchestration tools", "data pipelines"),
    ("role-based access controls, encryption, and data masking", "data privacy / security"),
    ("metadata management, data classification, and lineage tracking", "data governance"),
    ("Experience with server-side programming, APIs", "web development (full-stack)"),
    ("API, webhook, authentication, data synchronization", "APIs / REST"),
    ("data structures", "data structures / algorithms"),
    ("strong problem decomposition", "problem solving"),
    ("Reporting, Dashboards, and Performance Measurement", "KPIs/metrics"),
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


def test_oct_20_review_products_and_concepts():
    assert not _is_tool("demand generation / lead funnel (MQLs)")
    for product, platform in [("SOQL", "Salesforce/CRM"), ("Acumatica", "ERP (SAP/Oracle/Workday)")]:
        assert _is_tool(product), product
        assert product in taxonomy.TOOL_TYPES, product
        assert taxonomy.RELATED[product] == platform
        assert taxonomy.category(platform), platform


def test_oct_29_review_products_and_concepts():
    for name in ["software architecture / system design", "event-driven architecture", "AI-assisted coding",
                 "site reliability engineering (SRE)", "open-source contribution", "event tracking / instrumentation",
                 "concurrency / multithreading", "data science", "supply chain / inventory", "cryptography"]:
        assert not _is_tool(name), name
    for name in ["Snowpark", "Ruby on Rails", "Three.js / WebGL", "Unity / Unreal Engine",
                 "ORM (Hibernate / SQLAlchemy)", "Azure integration services (Logic Apps / Service Bus / Event Grid)"]:
        assert _is_tool(name), name
        assert name in taxonomy.TOOL_TYPES, name
    for product, platform in [("Snowpark", "Snowflake"), ("Ruby on Rails", "Ruby"), ("Three.js / WebGL", "JavaScript"),
                              ("Azure integration services (Logic Apps / Service Bus / Event Grid)", "Azure")]:
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
