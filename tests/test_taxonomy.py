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
    # Nov 7 2026 review.
    ("base pay benchmarking and pay band development", "benchmarking"),
    ("Recruitment Fraud Alert: Protect Yourself", "fraud / AML (financial crime)"),
    ("We use Tofu, a fraud detection tool, to validate the authenticity of applicants",
     "fraud / AML (financial crime)"),
    ("AI technologies used in our recruitment process undergo detailed risk assessments",
     "risk management / regulatory compliance"),
    ("admired a towering skyscraper", "web scraping"),
    ("Our Data Architecture & Engineering team works across AWS", "data architecture"),
    ("Salaire de base concurrentiel", "concurrency / multithreading"),
    ("Ability to handle multiple concurrent tasks", "concurrency / multithreading"),
    ("work closely with Engineering and SRE teams", "site reliability engineering (SRE)"),
    ("equivalence partitioning and boundary value analysis", "query / performance tuning"),
    ("make sure the data is right", "Zapier / n8n / Make"),
    ("networking events with the team", "networking (TCP/IP)"),
    ("access tokens and Excel files", "Microsoft Access"),
    ("Hugo Boss", "static site generators (Hugo / Docusaurus)"),
    ("MQTT, Kafka", "RabbitMQ / ActiveMQ / IBM MQ"),
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
    # Nov 7 2026 review: real posting wording.
    ("hands-on experience with Pytest, Pydantic and FastAPI", "Pydantic"),
    ("including scraping, proxy management and working with public APIs", "web scraping"),
    ("Familiarity with large-scale web scraping, crawling, and web data extraction", "web scraping"),
    ("Understanding of operating systems, software configuration, and basic networking concepts", "operating systems"),
    ("Understanding of operating systems, software configuration, and basic networking concepts", "networking (TCP/IP)"),
    ("scenario modelling, cash flow forecasting, leverage and liquidity analysis in Anaplan plus ad-hoc financial models",
     "financial analysis / FP&A"),
    ("forecasting and portfolio analysis across the RE Debt portfolio", "investment performance / attribution"),
    ("ad hoc research (benchmarking, peer and risk analysis)", "benchmarking"),
    ("ad hoc research (benchmarking, peer and risk analysis)", "risk management / regulatory compliance"),
    ("Supports fraud risk assessments, quality assurance, data validation", "risk management / regulatory compliance"),
    ("Statistics, Excel, SAS, R, SPSS, Python, VBA, SQL, Tableau, A/B Testing, Digital Marketing",
     "digital marketing / SEO / SEM"),
    ("Familiarity with technologies such as Spark, Kafka, Delta Lake, Unity Catalog, Dataplex, Dataflow",
     "Google Cloud Dataplex"),
    ("distributed processing, lakehouse architectures, streaming", "distributed systems"),
    ("experience with data architecture and governance", "data architecture"),
    ("High proficiency in Python, Spark, Hadoop tools (Hive, Impala, Airflow, NiFi), SQL", "Impala"),
    ("High proficiency in Python, Spark, Hadoop tools (Hive, Impala, Airflow, NiFi), SQL", "Apache NiFi"),
    ("Orchestration tools such as Apache Airflow, NiFi or Talend", "Talend"),
    ("Develop data processing jobs using PySpark/Spark and Python on platforms such as Cloudera and Databricks",
     "Cloudera"),
    ("Optimize pipeline performance and cost (partitioning, file formats, compute tuning, query patterns)",
     "query / performance tuning"),
    ("DevOps/CI-CD: Git, automated testing, release pipelines, observability", "CI/CD"),
    ("Experience with CI/CD (GitLab CI, GitHub Actions)", "CI/CD"),
    ("Build and support data ingestion, integration, and orchestration processes", "data pipelines"),
    ("3 years relevant experience in fraud prevention, fraud detection, transaction monitoring, or financial crime analytics",
     "fraud / AML (financial crime)"),
    ("Collaborates with Fraud Investigations, AML, Technology, Operations", "fraud / AML (financial crime)"),
    ("CFCI, CFE are considered an asset", "CFE / CFCI"),
    ("Working Knowledge of SQL Server, Power BI, PowerPivot, Dashboards and Data Visualization", "Power Pivot"),
    ("Familiarity with Python and basic machine-learning concepts is considered an asset", "machine learning"),
    ("Strong analytical, critical-thinking, and problem-solving skills", "critical thinking"),
    ("Ability to use approved generative-AI tools responsibly", "LLMs / generative AI"),
    ("Proficiency in SQL, Excel and Access", "Microsoft Access"),
    ("Cloud Run services and jobs, Cloud Scheduler, Cloud Storage, BigQuery", "Google Cloud Run"),
    ("Cloud Run services and jobs, Cloud Scheduler, Cloud Storage, BigQuery", "Google Cloud Scheduler"),
    ("credentials and access: rotation, least privilege, and immediate revocation", "IAM (identity and access management)"),
    ("integration components, including SSO, security, and messaging (Kafka or MQ)", "IAM (identity and access management)"),
    ("integration components, including SSO, security, and messaging (Kafka or MQ)", "RabbitMQ / ActiveMQ / IBM MQ"),
    ("Production experience with Redis, Elasticsearch, RabbitMQ, or Celery", "RabbitMQ / ActiveMQ / IBM MQ"),
    ("Familiarity with Canadian privacy law (PIPEDA, Alberta PIPA)", "data privacy / security"),
    ("Jira, confluence, Grafana, ClickHouse, and various NoSQL databases", "ClickHouse"),
    ("performance and monitoring with tools such as Splunk or Elastic", "Splunk"),
    ("SQL Server or PostgreSQL administration, performance tuning, replication, high availability, and disaster recovery",
     "high availability / disaster recovery"),
    ("1+ year working in a Database / SRE / Engineering-related role", "site reliability engineering (SRE)"),
    ("frameworks such as LangChain, AutoGen, or CrewAI", "CrewAI / AutoGen"),
    ("low-code orchestration (n8n, Make, Zapier or similar)", "Zapier / n8n / Make"),
    ("build reliable workflows using tools such as Make, Zapier, or n8n", "Zapier / n8n / Make"),
    ("static site generators like Hugo or Docusaurus, or documentation platforms built on NextJS, Astro",
     "static site generators (Hugo / Docusaurus)"),
    ("static site generators like Hugo or Docusaurus, or documentation platforms built on NextJS, Astro", "Next.js"),
    ("Familiarity with Markdown-based documentation or docs-as-code practices", "docs-as-code"),
    ("Familiarity with Markdown-based documentation or docs-as-code practices", "Markdown"),
    ("multi-format content output (HTML, JSON, XML, raw Markdown, PDF, ePub", "XML"),
    ("Experience with building APIs and services using SOAP", "APIs / REST"),
    ("Software development expertise, particularly large-scale, real-time embedded systems", "embedded systems"),
    ("Familiarity with developing software on multi-processor, highly concurrent systems", "concurrency / multithreading"),
    ("parallel and distributed computing, high-performance computing", "distributed systems"),
    ("cloud platforms (AWS, Azure, GCP) or virtualization (KVM, VMware, OpenStack)", "virtualization"),
    ("Basic networking and security knowledge (TCP/IP, firewalls, VPNs)", "network security (firewalls / VPNs)"),
    ("make recommendations on pricing through profitability analyses, market trends, and pricing optimization performance",
     "pricing analysis / strategy"),
    ("data platform modernization and cloud migration", "cloud migration"),
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


def test_nov_7_review_products_and_concepts():
    for name in ["benchmarking", "web scraping", "data architecture", "operating systems", "embedded systems",
                 "high availability / disaster recovery", "docs-as-code", "fraud / AML (financial crime)",
                 "digital marketing / SEO / SEM", "CFE / CFCI"]:
        assert not _is_tool(name), name
    for name in ["Pydantic", "Next.js", "CrewAI / AutoGen", "Cloudera", "Impala", "Apache NiFi", "Talend",
                 "ClickHouse", "Splunk", "Power Pivot", "Zapier / n8n / Make", "Google Cloud Run",
                 "Google Cloud Scheduler", "Google Cloud Dataplex", "RabbitMQ / ActiveMQ / IBM MQ",
                 "static site generators (Hugo / Docusaurus)"]:
        assert _is_tool(name), name
        assert name in taxonomy.TOOL_TYPES, name
    for product, platform in [("Next.js", "React"), ("Power Pivot", "Excel"), ("Cloudera", "Hadoop/Hive"),
                              ("Impala", "Hadoop/Hive"), ("Google Cloud Run", "GCP"),
                              ("Google Cloud Scheduler", "GCP"), ("Google Cloud Dataplex", "GCP")]:
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
