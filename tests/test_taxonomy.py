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
    # Skills review, Oct 30 2026.
    ("Go Fast, Be Agile: Widen our competitive advantage", "Agile/Scrum"),
    ("We use Tofu, a fraud detection tool, to validate the authenticity of applications",
     "fraud detection / prevention"),
    ("translating needs into clear, structured outputs", "LLM structured outputs"),
    ("turning physiological and behavioral data into safe, structured outputs", "LLM structured outputs"),
    ("building security guardrails directly into CI/CD pipelines", "AI guardrails / hallucination mitigation"),
    ("Anticipate failure modes, build guardrails, and follow through on post-incident learnings",
     "AI guardrails / hallucination mitigation"),
    ("multi-Agent AI design patterns", "design patterns"),
    ("Define and implement secure design patterns", "design patterns"),
    ("Senior Director of Data Science and the Data Science team", "data science"),
    ("Women in Data Science × SAP Case Competition, March 2024", "data science"),
    ("lead technical discussions with enterprise stakeholders", "advertising / ad tech"),
    ("SOC 2 Type II compliance", "security operations (SIEM / SOC)"),
    ("update the weights and biases of the network", "Weights & Biases"),
    ("Thanks, Erwin from the recruiting team", "erwin"),
    ("work in hybrid mode, or remotely", "Mode"),
    ("we make it easy to sip coffee", "telephony / VoIP (SIP, WebRTC)"),
    ("our cloud functions scale on demand", "Google Cloud Run / Cloud Functions"),
    ("Azure Cloud Storage accounts", "Google Cloud Storage"),
    ("summarize research findings", "Langfuse / Arize Phoenix"),
    ("Make sure you apply before Friday", "workflow automation (Zapier / n8n / Make)"),
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
    # Skills review, Oct 30 2026: real posting wording, new skills.
    ("Experience with Rust and/or Golang", "Rust"),
    ("Programming in Elixir, Go, Python, Rust, or similar languages", "Elixir"),
    ("frameworks such as Google's Agent Development Kit (ADK), LangChain, or equivalent", "Google ADK"),
    ("Skilled with data visualization libraries (D3, Leaflet, etc)", "D3.js"),
    ("Experience building and maintaining production Ruby on Rails applications", "Ruby on Rails"),
    ("using tools such as Tableau, Power BI, Mode, or similar technology", "Mode"),
    ("Snowflake, dbt, Hightouch, Fivetran, Looker, Stripe, Salesforce, Orb", "Hightouch"),
    ("Exposure to Stripe, Salesforce, or Orb in billing and finance contexts", "Orb"),
    ("Snowflake's unstructured data capabilities (Directory Tables, Scoped URLs, Snowpark)", "Snowpark"),
    ("Leverage Erwin Data Intelligence for metadata and lineage tracking", "erwin"),
    ("Strong understanding of data governance, data lineage, master data management, and data profiling",
     "master data management"),
    ("Instrument applications with tracing and structured logging (e.g. OpenTelemetry, Cloud Trace)", "OpenTelemetry"),
    ("Airflow / Cloud Composer, Dataflow, Kubeflow, or similar", "Kubeflow"),
    ("Langfuse, Arize Phoenix, Weights & Biases, Vertex AI Evaluation, or equivalent", "Weights & Biases"),
    ("Langfuse, Arize Phoenix, Weights & Biases, Vertex AI Evaluation, or equivalent", "Langfuse / Arize Phoenix"),
    ("primarily using Cloud Run, Cloud Functions, and Vertex AI", "Google Cloud Run / Cloud Functions"),
    ("Able to troubleshoot and debug issues on basic networking, knowledge of Wireshark", "Wireshark"),
    ("including code documentation (ie: Doxygen, Sphinx) and user guides", "Sphinx / Doxygen"),
    ("Telephony and voice infrastructure, including PSTN, SIP trunking, PBX, and call routing",
     "telephony / VoIP (SIP, WebRTC)"),
    ("access controls, and release management", "release management"),
    ("Microservices and event-driven architectures", "event-driven architecture"),
    ("Reliability engineering or SRE experience", "site reliability engineering (SRE)"),
    ("security tools such as SIEM, IDS, Anti-Virus, EDR, WAF, and DLP", "security operations (SIEM / SOC)"),
    ("designing, implementing, and maintaining cryptographic systems", "cryptography"),
    ("understanding of object-oriented coding and design, design patterns", "design patterns"),
    ("human-in-the-loop AI workflows", "human-in-the-loop"),
    ("Apply appropriate guardrails, input/output validation, and human-in-the-loop checks",
     "AI guardrails / hallucination mitigation"),
    ("Familiar with prompt engineering and techniques to reduce hallucination",
     "AI guardrails / hallucination mitigation"),
    ("Experiment with AI agents, tool/function calling, structured outputs", "LLM structured outputs"),
    ("Speech-to-Text, Text-to-Speech, Voice Activity Detection", "speech / voice AI"),
    ("Self-Correction and Reinforcement Learning from execution feedback", "reinforcement learning"),
    ("data cleaning, feature engineering, and dimensionality reduction", "dimensionality reduction"),
    ("Conduct model training and hyperparameter tuning", "hyperparameter tuning"),
    ("Bayesian methods, HMMs, graphical models, dimension reduction", "probabilistic graphical models / HMMs"),
    ("optimization, probability, statistical modeling, econometrics, or control theory", "econometrics"),
    ("apply data science to complex product and business problems", "data science"),
    ("low-code orchestration (n8n, Make, Zapier or similar)", "workflow automation (Zapier / n8n / Make)"),
    ("Fraud Prevention Analyst", "fraud detection / prevention"),
    ("Manage and resolve chargebacks, disputes, and payment reconciliation", "fraud detection / prevention"),
    ("Prior experience in e-commerce specifically", "e-commerce / online marketplaces"),
    ("preferably within a supply chain, retail, or consumer goods environment", "supply chain"),
    ("Familiarity with ads systems, auction theory, or related marketplace optimization problems",
     "advertising / ad tech"),
    ("No previous trust and safety experience is required", "trust & safety / content moderation"),
    ("data engineering, analytics engineering, or revenue operations context", "revenue operations (RevOps)"),
    ("familiar with post-silicon validation methodologies", "semiconductor / silicon validation"),
    # Fixes to existing entries.
    ("Azure Data Lake, Azure Synapse, and Data Bricks", "Databricks"),
    ("data pipelines, primarily utilizing SparkSQL and Pyspark", "Spark/PySpark"),
    ("Knowledge of data engineering concepts including data ingestion, integration, transformation", "data pipelines"),
    ("Strong command of at least one data orchestration tool", "data pipelines"),
    ("high standards for data accuracy and validation", "data quality / validation"),
    ("Perform data profiling and quality assessments", "data quality / validation"),
    ("privacy and regulatory standards (e.g., FOIP, GDPR)", "data privacy / security"),
    ("Exposure to infrastructure-as-code (Terraform, AWS CDK)", "Terraform/IaC"),
    ("Design and conduct A/B experiments", "A/B testing / experimentation"),
    ("design experiments, and interpret results", "A/B testing / experimentation"),
    ("offline evaluations, online experiments, and production monitoring", "A/B testing / experimentation"),
    ("offline evaluations, online experiments, and production monitoring", "LLM / AI evaluation"),
    ("Create evaluation sets and automated tests", "LLM / AI evaluation"),
    ("Build approaches for evaluating and testing AI systems", "LLM / AI evaluation"),
    ("Demonstrated learning agility, attention to detail", "curiosity / learning"),
    ("a demonstrated ability to pick up new languages quickly", "curiosity / learning"),
    ("Fast learner with good communication skills", "curiosity / learning"),
    ("Customer Acquisition Cost (CAC), Return on Ad Spend (ROAS)", "marketing analytics / attribution"),
    ("Experience with process modeling tools (e.g., Engage Process Modeler, Visio)", "process improvement"),
    ("Knowledge of common critical network protocols", "networking (TCP/IP)"),
    ("Applied understanding of the OSI model", "networking (TCP/IP)"),
    ("Experience in object detection, recognition, and tracking", "computer vision"),
    ("neural networks, and ensemble methods", "machine learning"),
    ("ingestion, parsing, chunking, embedding, indexing", "RAG (retrieval-augmented generation)"),
    ("Implement hybrid retrieval", "search / information retrieval"),
    ("agentic architectures, tool use or multi-agent workflows", "AI agents / agentic AI / MCP"),
    ("structured logging, metrics, distributed tracing", "pipeline monitoring / alerting"),
    ("balance between independent work and teamwork", "independent / self-starter"),
    ("API-based data connectors (REST/SOAP, webhooks, file-based transfers)", "APIs / REST"),
    ("RESTful APIs, and OAuth2", "IAM (identity and access management)"),
    ("BigQuery, Cloud Storage, and Dataflow", "Google Cloud Storage"),
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


def test_oct_30_review_products_and_concepts():
    for name in ["master data management", "design patterns", "telephony / VoIP (SIP, WebRTC)", "release management",
                 "event-driven architecture", "site reliability engineering (SRE)",
                 "security operations (SIEM / SOC)", "cryptography", "data science", "human-in-the-loop",
                 "fraud detection / prevention", "supply chain"]:
        assert not _is_tool(name), name
    for name in ["Elixir", "Google ADK", "D3.js", "Ruby on Rails", "Mode", "Hightouch", "Orb", "Snowpark", "erwin",
                 "OpenTelemetry", "Kubeflow", "Weights & Biases", "Langfuse / Arize Phoenix",
                 "Google Cloud Run / Cloud Functions", "Wireshark", "Sphinx / Doxygen",
                 "workflow automation (Zapier / n8n / Make)"]:
        assert _is_tool(name), name
        assert name in taxonomy.TOOL_TYPES, name
    for product, platform in [("Snowpark", "Snowflake"), ("Google Cloud Run / Cloud Functions", "GCP"),
                              ("Ruby on Rails", "Ruby"), ("Kubeflow", "MLOps"), ("D3.js", "JavaScript")]:
        assert taxonomy.RELATED[product] == platform
    for platform in set(taxonomy.RELATED.values()):
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
