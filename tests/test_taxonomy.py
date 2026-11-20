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
    # Daily review, Nov 13 2026.
    ("help drive cost optimization and cloud financial governance", "optimization / OR"),
    ("MORE OR LESS THE SAME", "HTML/CSS"),
    ("GitLab is the intelligent orchestration platform for DevSecOps", "data orchestration"),
    ("orchestration frameworks like Docker and Kubernetes", "data orchestration"),
    ("a container management/orchestration tool (e.g. Docker, Kubernetes)", "data orchestration"),
    ("an existing vacancy in our Investment Data Architecture (IDArch) team", "data architecture"),
    ("Our Data Architecture & Engineering team works across AWS", "data architecture"),
    ("collaborating with Data Science partners", "data science"),
    ("Data Science & AnalyticsPosted Sep 25, 2026", "data science"),
    ("Pacific Coastal Airlines (PCA) is looking for an Aircraft Maintenance Engineer", "dimensionality reduction"),
    ("Monitor and report on UX metrics and KPIs", "UI/UX design"),
    ("work with product managers, developers, QA, technical writers", "QA / UAT"),
    ("you'll also help stand up and run the infrastructure", "Agile/Scrum"),
    ("Standup desks can be requested too", "Agile/Scrum"),
    ("boundary value analysis, equivalence partitioning and state transition", "query / performance tuning"),
    ("fraud prevention, chargeback mitigation in electronic payments", "FinOps / cloud cost management"),
    ("Generalized Linear Models, Gradient Boosting", "Linear"),
    ("3D Geometry, Linear Algebra, Coordinate Transformations", "Linear"),
    ("Call of Duty is one of the most successful video game franchises", "video game / player analytics"),
    ("Administer the corporate capital asset management system", "investment / asset management"),
    ("Google Ads, LinkedIn Campaign Manager, and GTM reporting", "Google Tag Manager"),
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
    # Daily review, Nov 13 2026: real posting wording (job ids in the PR).
    ("Hands-on experience building agentic workflows with AI coding agents (e.g., Claude Code, OpenCode, or similar)",
     "AI-assisted development"),
    ("Practical proficiency with Python and coding agents", "AI-assisted development"),
    ("engineers using AI-assisted coding tools to accelerate reviews", "AI-assisted development"),
    ("Experience with multiple assisted coding environments", "AI-assisted development"),
    ("Creating standalone, proof-of-concept applications", "prototyping / proof of concept"),
    ("Enable proofs of concept and new analytics use cases", "prototyping / proof of concept"),
    ("research, data science, investment analytics, investment management, or data science", "data science"),
    ("Experience using Python for statistical modeling, machine learning, and production data science", "data science"),
    ("practices including technical design, solution development", "software architecture / system design"),
    ("Passion for clean code, scalable architecture", "clean / maintainable code"),
    ("Write clean, tested, maintainable code", "clean / maintainable code"),
    ("Support table retirement and technical debt reduction", "clean / maintainable code"),
    ("Proven experience translating complex UX/UI designs into responsive front-end code", "UI/UX design"),
    ("Integrating UX and UI designs into clean code", "UI/UX design"),
    ("Experience with a workflow orchestration tool (preferably Prefect)", "data orchestration"),
    ("batch and streaming data pipelines, integrations, and orchestration workflows", "data orchestration"),
    ("lakehouse architectures, streaming, APIs, orchestration, or data platform modernization", "data orchestration"),
    ("create medallion-style data layers", "medallion architecture (bronze / silver / gold)"),
    ("including incremental loads, partitioning, and CDC patterns", "incremental loading / CDC"),
    ("data modeling for analytics (dimensional modeling, incremental models, testing)", "incremental loading / CDC"),
    ("refined data architectures that have had a measurable impact", "data architecture"),
    ("Exposure to modern architectures such as microservices, serverless, or event-driven systems",
     "event-driven architecture / message queues"),
    ("Experience modernizing legacy data environments or migrating workloads to cloud platforms",
     "cloud migration / legacy modernization"),
    ("APIs, orchestration, or data platform modernization", "cloud migration / legacy modernization"),
    ("We're looking for a FinOps Data Engineer", "FinOps / cloud cost management"),
    ("Tagging policies, cost allocation, and chargeback/showback", "FinOps / cloud cost management"),
    ("Partner with IT, Engineering, Product, vulnerability management, security operations",
     "security operations / vulnerability management"),
    ("ensure data quality, integrity, and correct labeling", "data labeling / annotation"),
    ("Strong understanding of data quality, taxonomy design, labeling workflows", "data labeling / annotation"),
    ("data cleaning, feature engineering, and dimensionality reduction", "dimensionality reduction"),
    ("Conduct model training and hyperparameter tuning", "hyperparameter tuning"),
    ("Proficiency in Pandas, Polars, or similar", "Polars"),
    ("Experience with a BI tool such as ThoughtSpot, Looker, or Power BI", "ThoughtSpot"),
    ("Google Analytics (GA4), Google Tag Manager, Looker or Looker Studio, Adobe Analytics", "Google Tag Manager"),
    ("Google Analytics (GA4), Google Tag Manager, Looker or Looker Studio, Adobe Analytics", "Adobe Analytics"),
    ("Exposure to DevOps (YAML pipelines, Terraform/Bicep)", "YAML"),
    ("Snowflake, dbt, Hightouch, Fivetran, Looker", "Hightouch / reverse ETL"),
    ("Unity Catalog, Dataplex , Dataflow, Pub/Sub", "Google Cloud Dataplex"),
    ("comfortable picking up, Linear and Notion as the system of record", "Linear"),
    ("comfortable picking up, Linear and Notion as the system of record", "Notion"),
    ("Claude, Cursor, Linear, Supabase, Slack", "Linear"),
    ("data from web analytics, CRM, and marketing automation systems", "marketing automation"),
    ("Adobe Tags/Launch, Google Ads, LinkedIn Campaign Manager", "Google Ads"),
    ("platforms such as web analytics, paid media, marketing automation", "digital advertising / paid media"),
    ("uncovering actionable insights from player data, understanding player behaviour", "video game / player analytics"),
    ("Support experimentation initiatives across The Grounds, Meta, and Live Operations", "video game / player analytics"),
    ("Experience in asset management or financial services is strongly preferred", "investment / asset management"),
    ("experience in investment analytics, investment management, or data science", "investment / asset management"),
    ("exposure to FP&A, Demand/Supply Planning, or Supply Chain Management", "supply chain / demand planning"),
    ("Familiarity with billing systems, GAAP accounting, revenue recognition", "billing systems"),
    ("Flexibility and resourcefulness in navigating manual tasks", "resourcefulness"),
    ("You are a systems thinker and take ownership of your work", "systems thinking"),
    # Fixes to existing entries.
    ("Experience with ReactJS", "React"),
    ("Node.js (NestJS is a plus)", "Node.js"),
    ("Familiarity with LESS or SASS", "HTML/CSS"),
    ("Hands-on ETL/ELT with at least one Microsoft service (ADF, Synapse Pipelines)", "Microsoft Fabric / Azure Synapse / ADF"),
    ("Project experience with Microsoft Fabric (OneLake, Lakehouses)", "Microsoft Fabric / Azure Synapse / ADF"),
    ("Exposure to DevOps (YAML pipelines, Terraform/Bicep)", "Terraform/IaC"),
    ("Python, Terraform/ pulumi, Lambda, or Bash", "Terraform/IaC"),
    ("APIs, webhooks, configuration as code", "Terraform/IaC"),
    ("APIs, webhooks, configuration as code", "APIs / REST"),
    ("Experience with CI/CD processes and tools (e.g. TeamCity)", "CI/CD"),
    ("Develop CI / CD tools integration / operation", "CI/CD"),
    ("Linux, Agile, GitHub, Git, or SVN", "Git"),
    ("test-driven development", "testing (unit/automated)"),
    ("designing, building, and expanding test coverage", "testing (unit/automated)"),
    ("automation and UI testing frameworks such as Playwright", "testing (unit/automated)"),
    ("Solid knowledge of QA processes, testing methodologies", "QA / UAT"),
    ("maintain test scripts. Identify, document, and track software defects", "QA / UAT"),
    ("networking technologies, including routing, DNS, DHCP, VPN, and switching", "networking (TCP/IP)"),
    ("Knowledge of data warehousing and logical modeling", "data modeling"),
    ("validating hypotheses, and embedding machine learning models", "hypothesis testing / inference"),
    ("A/B testing, power analysis, quasi-experimental methods", "hypothesis testing / inference"),
    ("participate in planning, standups, and retrospectives", "Agile/Scrum"),
    ("Participate in daily stand-ups, design reviews", "Agile/Scrum"),
    ("Optimize pipeline performance and cost (partitioning, clustering, incremental models)", "query / performance tuning"),
    ("productionize reporting datasets, improve data reliability, investigate discrepancies", "pipeline monitoring / alerting"),
    ("freshness, completeness, accuracy, volume, and schema validation", "data quality / validation"),
    ("ETL/ELT, distributed processing, lakehouse architectures", "distributed systems"),
    ("numerical computing, performance optimization, and Python", "mathematics (linear algebra, calculus)"),
    ("workflows using Python and command-line tools", "Bash/Shell"),
    ("recommendation, trend analysis, scoring", "data analysis"),
    ("Curiosity about B2B marketing measurement, digital analytics, campaign performance",
     "marketing analytics / attribution"),
    ("single sign-on (SSO), SAML/OIDC, multifactor authentication (MFA)", "IAM (identity and access management)"),
    ("Demonstrated curiosity, learning agility", "curiosity / learning"),
    ("A curious, growth-oriented mindset", "curiosity / learning"),
    ("self-motivation", "independent / self-starter"),
    ("runbooks, operational runbooks, deployment guides", "documentation"),
    ("reliable batch and streaming data pipelines", "data pipelines"),
    ("batch processing jobs", "data pipelines"),
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


def test_nov_13_review_products_and_concepts():
    for name in ["UI/UX design", "data orchestration", "incremental loading / CDC", "software architecture / system design",
                 "AI-assisted development", "FinOps / cloud cost management", "marketing automation", "data science",
                 "video game / player analytics", "resourcefulness"]:
        assert not _is_tool(name), name
    for name in ["Polars", "ThoughtSpot", "Google Tag Manager", "Adobe Analytics", "Google Cloud Dataplex",
                 "Hightouch / reverse ETL", "Linear", "Notion", "Google Ads"]:
        assert _is_tool(name), name
        assert name in taxonomy.TOOL_TYPES, name
    for product, platform in [("Google Cloud Dataplex", "GCP"), ("Google Tag Manager", "Google Analytics")]:
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
