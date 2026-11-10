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
    # Daily review, Nov 10 2026.
    ("Drive cost optimization across GCP and AWS", "optimization / OR"),
    ("Databricks AI/BI, Tableau, or similar reporting tools", "AI (any mention)"),
    ("companies with the highest probability of reaching $1 billion in annual revenue", "statistics"),
    ("Maintain clear test plans, test cases, defect reports and regression suites", "reporting"),
    ("Content deduplication: SHA256 hashing prevents re-processing identical uploads", "data quality / validation"),
    ("Amazon Web Services' Cloud Storage, AWS S3, is one of the largest distributed storage systems",
     "Google Cloud Storage"),
    ("Solid understanding of Composer and dependency management", "Google Cloud Composer"),
    ("SAP authorization objects; SAP BTP application security", "secure coding / OWASP"),
    ("Must be able to obtain work authorization in the country of employment",
     "authentication / authorization (OAuth, SSO)"),
    ("Legal authorization to work in the U.S. indefinitely is required", "authentication / authorization (OAuth, SSO)"),
    ("health benefits, retirement savings plans, and paid time off", "FinOps / cloud cost management"),
    ("caching, batching, streaming responses, and right-sizing model selection to the task",
     "FinOps / cloud cost management"),
    ("marry the right product to the right sizes of the boxes", "FinOps / cloud cost management"),
    ("Use and evaluate AI developer tooling, including Copilot, Claude Code, Codex",
     "platform engineering / developer tooling"),
    ("design of piping system design for buildings", "software architecture / system design"),
    ("3. Technical Skills Evaluation - 60min Pair Programming", "pair programming"),
    ("pairing fast generation with the sharp judgment needed", "pair programming"),
    ("Workday differentiates across the Finance landscape versus legacy platforms", "legacy systems / modernization"),
    ("All hiring decisions are made by human reviewers.", "human-in-the-loop AI"),
    ("A human reviews each application, with the AI assessment as just one input", "human-in-the-loop AI"),
    ("proud members of the Diversity Mark NI initiative as a Bronze Member", "medallion architecture (bronze / silver / gold)"),
    ("we have great expectations for this role", "Great Expectations / Soda"),
    ("StackAdapt seamlessly connects brand and performance marketing", "digital advertising / performance marketing"),
    ("an AI-powered performance marketing agency", "digital advertising / performance marketing"),
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
    # Daily review, Nov 10 2026: real posting wording.
    ("Google Cloud: Cloud Run services and jobs, Cloud Scheduler, Cloud Storage, BigQuery", "Google Cloud Run"),
    ("Google Cloud: Cloud Run services and jobs, Cloud Scheduler, Cloud Storage, BigQuery", "Google Cloud Scheduler"),
    ("Google Cloud: Cloud Run services and jobs, Cloud Scheduler, Cloud Storage, BigQuery", "Google Cloud Storage"),
    ("Cloud Run, Cloud Functions, Pub/Sub", "Google Cloud Functions"),
    ("GCP Cloud Storage, Composer, IAM, Dataflow, Pub/Sub", "Google Cloud Composer"),
    ("Familiarity with Entra ID (Azure AD), SSO, OAuth, OpenID Connect, LDAP",
     "Microsoft Entra ID / Active Directory"),
    ("Familiarity with Entra ID (Azure AD), SSO, OAuth, OpenID Connect, LDAP",
     "authentication / authorization (OAuth, SSO)"),
    ("Basic understanding of authentication, authorization, identity management",
     "authentication / authorization (OAuth, SSO)"),
    ("CI/CD tools such as GitHub Actions or ArgoCD", "Argo CD / GitOps"),
    ("modern application security concepts", "secure coding / OWASP"),
    ("Experience in cloud engineering, infrastructure, DevOps, or FinOps", "FinOps / cloud cost management"),
    ("cloud cost-management tools such as AWS Cost Explorer/CUR, CloudHealth", "FinOps / cloud cost management"),
    ("rightsizing recommendations", "FinOps / cloud cost management"),
    ("build automation, developer tooling, AI-enabled workflows", "platform engineering / developer tooling"),
    ("join our Platform Engineering team", "platform engineering / developer tooling"),
    ("grow skills in system design, coding best practices", "software architecture / system design"),
    ("Write clean, maintainable and testable code", "clean / maintainable code"),
    ("staging vs. modeled layers, incremental loads, deduplication, and idempotent design",
     "incremental loading / CDC"),
    ("staging vs. modeled layers, incremental loads, deduplication, and idempotent design", "idempotency"),
    ("staging vs. modeled layers, incremental loads, deduplication, and idempotent design",
     "data quality / validation"),
    ("Build dbt models, tests, docs, macros and incremental logic", "incremental loading / CDC"),
    ("near-real-time change data capture", "incremental loading / CDC"),
    ("Own reliable Bronze layer ingestion for your assigned sources", "medallion architecture (bronze / silver / gold)"),
    ("Develop and support bronze, silver, and gold data models", "medallion architecture (bronze / silver / gold)"),
    ("Great Expectations or Soda Core", "Great Expectations / Soda"),
    ("collaborate with pair programming", "pair programming"),
    ("Help junior engineers grow through pairing and knowledge sharing", "pair programming"),
    ("migration of utility billing data from legacy systems", "legacy systems / modernization"),
    ("migration of utility billing data from legacy systems", "billing systems"),
    ("modernizing legacy data environments or migrating to cloud", "cloud migration"),
    ("Experience with contact centre modernization, cloud migration, and AI solutions", "cloud migration"),
    ("Build and demonstrate prototypes and proofs of value", "prototyping / proof of concept"),
    ("Experience in data science and machine learning", "data science"),
    ("automated graders, human review and production monitoring", "human-in-the-loop AI"),
    ("ingesting data from Google Ads, Meta Ads, and Microsoft/Bing Ads APIs",
     "ad platforms (Google / Meta / Microsoft Ads)"),
    ("Familiarity with LeadPerfection", "LeadPerfection"),
    ("Contribute to capacity planning and cost optimisation", "capacity planning"),
    ("Partner with performance marketing teams", "digital advertising / performance marketing"),
    ("full-funnel performance across GA4, paid search, social campaigns",
     "digital advertising / performance marketing"),
    ("Familiarity with billing systems, GAAP accounting", "billing systems"),
    # Fixes to existing entries.
    ("dbt tests, data-quality checks", "data quality / validation"),
    ("Data contract and schema validation experience", "data quality / validation"),
    ("Experience with non-relational databases", "NoSQL"),
    ("database schemas, data profiling", "relational databases / database design"),
    ("database schemas, data profiling", "data quality / validation"),
    ("real-time event streaming systems", "real-time / streaming data"),
    ("rotation, least privilege, and immediate revocation", "IAM (identity and access management)"),
    ("privacy laws (PIPA) and data sovereignty", "data privacy / security"),
    ("Google Drive and Google Docs", "Google Sheets / Workspace"),
    ("Jenkins, GitLab CI, CircleCI or similar", "CI/CD"),
    ("Basic statistics (probability, correlation, regression)", "statistics"),
    ("Build ranking systems for candidates", "recommendation systems"),
    ("evaluate prompts, interview strategies, scoring rubrics", "LLM / AI evaluation"),
    ("monitoring and logging, alerting", "pipeline monitoring / alerting"),
    ("Experience with Git, code review, automated testing, CI/CD, logging, and monitoring",
     "pipeline monitoring / alerting"),
    ("solution documentation, runbooks, and handover materials", "documentation"),
    ("Superior strategic writing skills", "communication"),
    ("navigating ambiguous requirements", "adaptability"),
    ("Lead technical demonstrations and knowledge-transfer sessions", "teaching / knowledge sharing"),
    ("notebook-based tools for data wrangling, exploratory analysis", "data analysis"),
    ("Design test strategies for data pipelines", "QA / UAT"),
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


def test_nov_10_review_products_and_concepts():
    for name in ["authentication / authorization (OAuth, SSO)", "FinOps / cloud cost management",
                 "platform engineering / developer tooling", "software architecture / system design",
                 "clean / maintainable code", "pair programming", "legacy systems / modernization",
                 "cloud migration", "idempotency", "prototyping / proof of concept", "incremental loading / CDC",
                 "medallion architecture (bronze / silver / gold)", "capacity planning", "data science",
                 "human-in-the-loop AI", "digital advertising / performance marketing", "billing systems"]:
        assert not _is_tool(name), name
    for product, platform in [("Google Cloud Run", "GCP"), ("Google Cloud Functions", "GCP"),
                              ("Google Cloud Scheduler", "GCP"), ("Microsoft Entra ID / Active Directory", "Azure"),
                              ("Argo CD / GitOps", "Kubernetes"), ("LeadPerfection", "Salesforce/CRM")]:
        assert _is_tool(product), product
        assert product in taxonomy.TOOL_TYPES, product
        assert taxonomy.RELATED[product] == platform
        assert taxonomy.category(platform), platform
    for product in ["Great Expectations / Soda", "ad platforms (Google / Meta / Microsoft Ads)"]:
        assert _is_tool(product), product
        assert product in taxonomy.TOOL_TYPES, product


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
