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


# Daily review, Nov 12 2026: real posting wording for each added skill.
@pytest.mark.parametrize("text, skill", [
    ("Programming in Elixir, Go, Python, Rust, or similar languages", "Elixir"),
    ("solutions using Salesforce Apex, Flow, and Agentforce", "Salesforce Apex"),
    ("Utilize bulkified Apex Triggers, Queueable Apex", "Salesforce Apex"),
    ("analytics dashboards on Dash Enterprise", "Streamlit / Dash / Shiny"),
    ("web applications using frameworks such as Dash and Streamlit", "Streamlit / Dash / Shiny"),
    ("data visualization tools (e.g. Tableau, PowerBi, R Shiny)", "Streamlit / Dash / Shiny"),
    ("PyTorch, Kubernetes/EKS, NVIDIA Triton, Ray, AWS", "Ray"),
    ("Google Analytics (GA4), Google Tag Manager, Looker", "Google Tag Manager"),
    ("Looker Studio, Adobe Analytics, Adobe Tags/Launch", "Adobe Analytics"),
    ("a BI tool such as ThoughtSpot, Looker, or Power BI", "ThoughtSpot"),
    ("Power BI * Tableau * Cognos * BusinessObjects * SSRS", "SAP BusinessObjects"),
    ("Hands-on experience with Informatica PowerCenter and/or Informatica IICS", "Informatica"),
    ("event-driven microservices with RabbitMQ at the center", "RabbitMQ"),
    ("Working with Aveva PI AF, EF and other PI tools", "AVEVA PI / OSIsoft PI"),
    ("create medallion-style data layers", "medallion architecture (bronze / silver / gold)"),
    ("Own reliable Bronze layer ingestion", "medallion architecture (bronze / silver / gold)"),
    ("incremental loads, partitioning, and CDC patterns", "incremental loading / CDC"),
    ("near-real-time change data capture", "incremental loading / CDC"),
    ("incremental loads, deduplication, and idempotent design", "idempotency"),
    ("S3, Glue, Athena, Redshift, Step Functions, Lambda", "AWS Step Functions"),
    ("GCP (BigQuery, Cloud SQL, Cloud Run) and AWS", "Google Cloud Run"),
    ("GCP (BigQuery, Cloud SQL, Cloud Run) and AWS", "Google Cloud SQL"),
    ("GCP services - Cloud Run, Cloud Functions, and Pub/Sub", "Google Cloud Functions"),
    ("BigQuery, Cloud Storage, Cloud Dataflow, and Dataproc", "Google Cloud Dataproc"),
    ("BigQuery, Cloud Storage, Cloud Dataflow, and Dataproc", "Google Cloud Storage"),
    ("including Azure Web Apps, Functions, and Container Jobs", "Azure Functions"),
    ("Azure Databricks, Azure Blob, Azure SQL", "Azure Blob / Data Lake Storage"),
    ("Azure Databricks, Azure Blob, Azure SQL", "Azure SQL Database"),
    ("Azure Integration Services (Logic Apps, API Management, Service Bus & Event Grid)", "Azure Logic Apps / Service Bus"),
    ("Azure SQL), Azure Active Directory and Azure Monitor", "Microsoft Entra ID / Active Directory"),
    ("scikit-learn, pandas, NumPy, XGBoost, Kubeflow", "Kubeflow"),
    ("Familiarity with message queues or event-driven systems", "event-driven architecture / message queues"),
    ("Experience with Celery, Redis, or background task processing", "event-driven architecture / message queues"),
    ("writing clean and reusable code", "clean / maintainable code"),
    ("You strive for code that's readable, testable, and maintainable", "clean / maintainable code"),
    ("Understanding of software architecture fundamentals and scalable design", "software architecture / system design"),
    ("Creating standalone, proof-of-concept applications", "prototyping / proof of concept"),
    ("Rapidly prototype directly in Dash", "prototyping / proof of concept"),
    ("Experience modernizing legacy data environments", "legacy systems / modernization"),
    ("migrating workloads to cloud platforms", "cloud migration"),
    ("Interest in AI-enabled workflows, automation, or applied data science", "data science"),
    ("large language models (LLMs), reinforcement learning and agentic workflows", "reinforcement learning"),
    ("probability, statistics, and econometric methods", "econometrics"),
    ("Use AI coding tools to move faster", "AI-assisted development"),
    ("Familiarity with LLMs and coding agents, including tool use", "AI-assisted development"),
    ("human-in-the-loop AI workflows", "human-in-the-loop AI"),
    ("output validation, and human review for sensitive workflows", "human-in-the-loop AI"),
    ("Develop and improve annotation workflows for video", "data labeling / annotation"),
    ("ensure data quality, integrity, and correct labeling", "data labeling / annotation"),
    ("Apply UI/UX principles to create consistent and responsive applications", "UI/UX design"),
    ("Familiarity with web accessibility or component-driven development", "web accessibility (WCAG)"),
    ("working from designs in Figma", "Figma"),
    ("ingesting data from Google Ads, Meta Ads, and Microsoft/Bing Ads APIs", "ad platforms (Google / Meta / Microsoft Ads)"),
    ("CRM data pipelines (Salesforce, HubSpot, LeadPerfection)", "LeadPerfection"),
    ("Great Expectations or Soda Core", "Great Expectations / Soda"),
    ("sanction screening and transaction monitoring platforms", "fraud / financial crime (AML)"),
    ("fraud detection", "fraud / financial crime (AML)"),
    ("forecast used by the Demand Planning team", "supply chain / demand planning"),
    ("Credit scoring, underwriting, admissions", "credit risk / credit decisioning"),
    ("security master, pricing master, and market reference data", "investment data (security master / fixed income)"),
    ("reference data across equity, fixed income, and derivatives", "investment data (security master / fixed income)"),
    ("Evaluate the accuracy of backtesting frameworks", "backtesting / systematic trading"),
    ("Familiarity with billing systems, GAAP accounting", "billing systems"),
    ("Background in performance marketing, ad-tech", "digital advertising / performance marketing"),
    ("a resourceful and curious Full Stack Software Engineer", "resourcefulness"),
    ("are a systems thinker, and take ownership", "systems thinking"),
    ("CFCI, CFE are considered an asset", "fraud certification (CFE / CAMS)"),
    ("Bilingualism (French and English) is preferred", "French (bilingual)"),
    # Fixes to existing entries.
    ("schema definition languages (e.g. DDL, SDL, XSD, RDF)", "SQL"),
    ("PowerPivot", "Excel"),
    ("Generalized Linear Models", "regression"),
    ("Probabilistic Calibration", "model evaluation/validation"),
    ("precision, recall, F1, and confusion matrices", "model evaluation/validation"),
    ("exponential smoothing, moving averages, seasonality", "time series"),
    ("forecasting models (e.g. Prophet)", "time series"),
    ("geo-based incrementality experiments", "A/B testing / experimentation"),
    ("post-mortems", "incident response / on-call"),
    ("runbooks", "documentation"),
    ("Perform data profiling, cleansing, reconciliation", "data quality / validation"),
    ("data contracts and schema validation", "data quality / validation"),
    ("business glossary terms, data definitions", "data governance"),
    ("least-privilege access practices", "IAM (identity and access management)"),
    ("vector databases (LanceDB, Milvus, Weaviate)", "vector databases"),
    ("embedding models (sentence transformers)", "embeddings"),
    ("interest in multi-agent systems", "AI agents / agentic AI / MCP"),
    ("DevSecOps practices and tools", "DevOps"),
    ("Transformers, CNNs, GNNs", "deep learning / neural nets"),
    ("NVIDIA Triton", "model serving / inference optimization"),
    ("Kubernetes/EKS", "Kubernetes"),
    ("intelligent document processing", "unstructured data / OCR"),
    ("the semantic layer that supports natural language query (NLQ)", "text-to-SQL / conversational analytics"),
    ("public API and webhooks", "APIs / REST"),
    ("backend development using Node.js (NestJS is a plus)", "Node.js"),
    ("Exposure to DevOps (YAML pipelines, Terraform/Bicep)", "Terraform/IaC"),
    ("Contribute to infrastructure as code (AWS CDK or Terraform)", "Terraform/IaC"),
    ("MLflow, Weights & Biases, DVC", "MLOps"),
    ("routing, DNS, DHCP, VPN, and switching", "networking (TCP/IP)"),
    ("Amazon Aurora", "Amazon RDS"),
    ("Optimize pipeline performance and cost (partitioning, clustering, incremental models)", "query / performance tuning"),
    ("process maps, RACI matrices, procedures", "process improvement"),
    ("Data Bricks", "Databricks"),
    ("machine-learning", "machine learning"),
    ("critical-thinking", "critical thinking"),
    ("approach ambiguous problems with structure", "adaptability"),
    ("data exploration", "data analysis"),
])
def test_nov_12_review_skills(text, skill):
    assert skill in taxonomy.find(text)


@pytest.mark.parametrize("text, wrong", [
    ("Respawn Entertainment is the studio behind Apex Legends", "Salesforce Apex"),
    ("operating related instrument such as KingFisher Apex and LabChip", "Salesforce Apex"),
    ("Please contact Ray Smith with questions", "Ray"),
    ("our GTM teams: Sales, Customer Success, and Revenue Operations", "Google Tag Manager"),
    ("custom business objects, condition rules, and workflow routings", "SAP BusinessObjects"),
    ("the largest community of 300,000 local service businesses", "Azure Logic Apps / Service Bus"),
    ("how Workday differentiates versus legacy platforms", "legacy systems / modernization"),
    ("We welcome people of colour (POC) to apply", "prototyping / proof of concept"),
    ("All hiring decisions are made by human reviewers", "human-in-the-loop AI"),
    ("A human reviews each application", "human-in-the-loop AI"),
    ("a Bronze Member of the association", "medallion architecture (bronze / silver / gold)"),
    ("following CDC guidelines", "incremental loading / CDC"),
    ("connects brand and performance marketing", "digital advertising / performance marketing"),
    ("or even personal logistics like childcare and pet care", "supply chain / demand planning"),
    ("the largest supply chain knowledge asset", "supply chain / demand planning"),
    ("stocks, ETFs, options, crypto, fixed income, 24/5 trading", "investment data (security master / fixed income)"),
    ("completion of the CPA Common Final Examination (CFE).", "fraud certification (CFE / CAMS)"),
    ("English French Math Science Coding Instructor", "French (bilingual)"),
    ("techniques such as equivalence partitioning and state transition", "query / performance tuning"),
    ("econometrics", "KPIs/metrics"),
    ("Exposure to DevOps (YAML pipelines, Terraform/Bicep)", "data pipelines"),
    ("SHA256 content deduplication of uploads", "data quality / validation"),
    ("We have great expectations for this role", "Great Expectations / Soda"),
    ("Join our Data Science team", "data science"),
    ("Our office is in Aurora, Ontario", "Amazon RDS"),
    ("Amazon Web Services' Cloud Storage, AWS S3", "Google Cloud Storage"),
    ("eligible for an F1 visa", "model evaluation/validation"),
    ("the desktop fetches that one source when the cloud run has already happened", "Google Cloud Run"),
    ("Collaborate with product managers, UX designers, engineers", "UI/UX design"),
])
def test_nov_12_review_false_matches(text, wrong):
    assert wrong not in taxonomy.find(text)


def test_nov_12_review_products_and_concepts():
    for name in ["clean / maintainable code", "AI-assisted development", "medallion architecture (bronze / silver / gold)",
                 "UI/UX design", "event-driven architecture / message queues", "data science", "French (bilingual)",
                 "fraud / financial crime (AML)"]:
        assert not _is_tool(name), name
    for product, platform in [("Google Cloud Run", "GCP"), ("Azure Functions", "Azure"), ("AWS Step Functions", "AWS"),
                              ("Salesforce Apex", "Salesforce/CRM"), ("Google Tag Manager", "Google Analytics"),
                              ("Streamlit / Dash / Shiny", "Python"), ("Kubeflow", "Kubernetes"), ("Figma", "UI/UX design")]:
        assert _is_tool(product), product
        assert product in taxonomy.TOOL_TYPES, product
        assert taxonomy.RELATED[product] == platform
        assert taxonomy.category(platform), platform
    for name in ["ThoughtSpot", "SAP BusinessObjects", "Informatica", "RabbitMQ", "Ray", "Great Expectations / Soda",
                 "AVEVA PI / OSIsoft PI", "Adobe Analytics"]:
        assert _is_tool(name) and name in taxonomy.TOOL_TYPES, name
