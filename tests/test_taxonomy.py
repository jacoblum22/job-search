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


# Daily review, Nov 14 2026: real posting wording.
@pytest.mark.parametrize("text, skill", [
    ("Understanding of regular expressions (RegEx) for data validation and pattern recognition.",
     "regular expressions (regex)"),
    ("Scripting experience (e.g., JavaScript / Google Apps Script or Python).", "Google Apps Script"),
    ("Experience with a web framework such as Express, Next.js, or similar.", "Next.js"),
    ("Experience with a web framework such as Express, Next.js, or similar.", "Express"),
    ("Strong in React, Node.js, Express, and databases (PostgreSQL, MongoDB).", "Express"),
    ("Python-based web applications using frameworks such as Dash and Streamlit.", "Streamlit"),
    ("Python-based web applications using frameworks such as Dash and Streamlit.", "Plotly Dash"),
    ("including state management and basic forms", "state management (Redux)"),
    ("Apply UI/UX principles to create consistent and responsive applications", "UI/UX design"),
    ("Apply UI/UX principles to create consistent and responsive applications", "responsive design"),
    ("Comfort with HTML and CSS, responsive layouts, and common web patterns", "responsive design"),
    ("Knowledge of web accessibility standards is considered an asset.", "web accessibility (WCAG)"),
    ("Experience with e-commerce, design systems, or component libraries.", "design systems / component libraries"),
    ("Experience with analytical data models, ideally Bronze/Silver/Gold or dimensional models",
     "medallion architecture (bronze / silver / gold)"),
    ("incremental loads, partitioning, and CDC patterns", "incremental loading / CDC"),
    ("Knowledge of web scraping technologies, Scrapy, or browser automation tools", "web scraping"),
    ("Write clean, well-documented, and testable code following engineering best practices",
     "clean / maintainable code"),
    ("Write clear, maintainable code and basic tests", "clean / maintainable code"),
    ("ensure it is functional and follows clean-code principles", "clean / maintainable code"),
    ("Experience with serverless architectures or event-driven design patterns",
     "software architecture / design patterns"),
    ("Integrate with databases, message queues, cloud services, and third-party APIs",
     "event-driven architecture / message queues"),
    ("Background in performance optimization, caching strategies, or high-throughput systems", "caching"),
    ("post-incident reviews, service-level objectives (SLOs), and error budgets",
     "site reliability engineering (SRE / SLOs)"),
    ("at least four years of experience in site reliability engineering (SRE)",
     "site reliability engineering (SRE / SLOs)"),
    ("FinOps, cloud cost management, and chargeback/showback reporting", "FinOps / cloud cost management"),
    ("Manage Azure infrastructure, including Azure Web Apps, Functions, and Container Jobs",
     "Azure Functions / App Service"),
    ("participate in the data science lifecycle to develop and deploy analytical models", "data science"),
    ("including descriptive statistics, forecasting, economic modeling, exploratory analysis",
     "econometrics / economic modeling"),
    ("Hands-on experience with AI coding agents and development tools such as Claude Code",
     "AI-assisted development"),
    ("Use AI assisted tools, such as Claude Code, in a disciplined way", "AI-assisted development"),
    ("Linear and Notion as the system of record", "Linear"),
    ("Linear and Notion as the system of record", "Notion"),
    ("tools like Claude, Cursor, Linear, Supabase, Slack.", "Linear"),
    ("tools like Claude, Cursor, Linear, Supabase, Slack.", "Slack"),
    ("integrations across Rootly, PagerDuty, Jira, Confluence, Slack, and the service catalog", "Slack"),
    ("no-code/low-code automation (Zapier, Power Automate, n8n)", "workflow automation tools (Zapier, n8n, Make)"),
    ("Power Automate/n8n/Zapier/Make.", "workflow automation tools (Zapier, n8n, Make)"),
    ("enterprise platforms (Salesforce, Greenhouse, Dayforce)", "HRIS (Workday HCM, Dayforce, SuccessFactors)"),
    ("experience in data engineering, analytics engineering, or a technical RevOps / BizOps role",
     "RevOps / sales operations"),
    ("Experience in Property & Casualty insurance is an asset", "insurance (P&C)"),
    ("Experience in the automotive industry, dealership operations, automotive finance", "automotive industry"),
    ("Strong systems thinking and problem-solving", "systems thinking"),
    ("Deep knowledge of data management or investment analytics; systems thinker", "systems thinking"),
])
def test_nov_14_review_new_skills(text, skill):
    assert skill in taxonomy.find(text)


# Fixes to existing entries, Nov 14 2026.
@pytest.mark.parametrize("text, skill", [
    ("React on the front end, Node on the back end", "Node.js"),
    ("Software Engineer - React, Node, TypeScript & AI Coding Tools", "Node.js"),
    ("Python and command-line tools", "Bash/Shell"),
    ("TypeScript, Vue.js, HTML, and CSS/LESS.", "HTML/CSS"),
    ("Experience with CSS preprocessors like SASS or LESS is a plus.", "HTML/CSS"),
    ("Ability to perform univariate analytic analysis", "data analysis"),
    ("Conduct exploratory analyses and data set characterizations.", "data analysis"),
    ("Analyze and profile data across enterprise systems", "data quality / validation"),
    ("Perform data quality, reconciliation, and validation activities", "data reconciliation"),
    ("Experience with Git/GitHub or other source control tools.", "Git"),
    ("Terraform/ pulumi", "Terraform/IaC"),
    ("infrastructure-as-code", "Terraform/IaC"),
    ("Maintain deployed models by running and delivering model output", "MLOps"),
    ("unit-testing", "testing (unit/automated)"),
    ("numerical computing", "mathematics (linear algebra, calculus)"),
    ("JD Edwards data gathering/manipulation experience would be an asset", "ERP (SAP/Oracle/Workday)"),
    ("Evaluate AI-generated outputs to ensure they meet business requirements", "LLM / AI evaluation"),
    ("Create and refine prompts that improve productivity, quality, and consistency.", "prompt engineering"),
    ("Ability to develop effective prompts and assess AI-generated outputs.", "prompt engineering"),
    ("3-5 years in data analysis, business systems analysis, data integration", "requirements gathering"),
    ("Knowledge of authentication, authorization, and security best practices",
     "IAM (identity and access management)"),
    ("Understanding of Okta SSO integration", "IAM (identity and access management)"),
    ("take initiative, drive execution of systems projects", "independent / self-starter"),
])
def test_nov_14_review_fixes(text, skill):
    assert skill in taxonomy.find(text)


@pytest.mark.parametrize("text, wrong", [
    ("Experience participating in process improvement or operational excellence initiatives",
     "independent / self-starter"),
    ("complete your CIP, FCIP, CRM or other courses desired", "Salesforce/CRM"),
    ("The British Columbia CRISM Node is housed at the BC Centre on Substance Use", "Node.js"),
    ("Advanced Node Layout: apply FinFET layout rules", "Node.js"),
    ("You will do less manual work", "HTML/CSS"),
    ("select the option to use your profile data for Any Roles Globally", "data quality / validation"),
    ("Letters of Authorization, and channel price files", "IAM (identity and access management)"),
    ("Ensure that a human always reviews AI-generated output", "LLM / AI evaluation"),
    ("Metrolinx runs GO Transit, UP Express and PRESTO", "Express"),
    ("in a dash of time", "Plotly Dash"),
    ("improve the user experience for customers", "UI/UX design"),
    ("Please let us know of any accessibility needs during the recruitment process", "web accessibility (WCAG)"),
    ("We design systems that scale", "design systems / component libraries"),
    ("Design systems using LLMs to ingest feature specifications", "design systems / component libraries"),
    ("CDC guidelines for public health reporting", "incremental loading / CDC"),
    ("clean and validate data before loading", "clean / maintainable code"),
    ("Systems design integrating multiple perspectives", "software architecture / design patterns"),
    ("fraud prevention, chargeback mitigation in electronic payments", "FinOps / cloud cost management"),
    ("cost allocation and month-end close", "FinOps / cloud cost management"),
    ("Data Science partners across the business", "data science"),
    ("Partner with Risk, Data Science, Engineering and Product.", "data science"),
    ("Women in Data Science datathon", "data science"),
    ("Linear regression and classification", "Linear"),
    ("Linear, logistic and polynomial regression", "Linear"),
    ("a notion of fairness", "Notion"),
    ("We work with companies like Slack, LaunchDarkly, and Vanguard", "Slack"),
    ("an impromptu quote from Arjun in our company Slack", "Slack"),
    ("Make sure your data is accurate", "workflow automation tools (Zapier, n8n, Make)"),
    ("life insurance, staff insurance discounts", "insurance (P&C)"),
    ("our underwriting platform for partnered merchants", "insurance (P&C)"),
    ("Automotive benefits and transit passes", "automotive industry"),
])
def test_nov_14_review_false_matches(text, wrong):
    assert wrong not in taxonomy.find(text)


def test_nov_14_review_products_and_concepts():
    for name in ["regular expressions (regex)", "UI/UX design", "clean / maintainable code", "caching",
                 "AI-assisted development", "state management (Redux)",
                 "medallion architecture (bronze / silver / gold)", "site reliability engineering (SRE / SLOs)",
                 "data science", "insurance (P&C)", "systems thinking"]:
        assert not _is_tool(name), name
    for product, platform in [("Google Apps Script", "Google Sheets / Workspace"), ("Next.js", "React"),
                              ("Express", "Node.js"), ("Streamlit", "Python"),
                              ("Plotly Dash", "matplotlib/seaborn/plotly"), ("Azure Functions / App Service", "Azure"),
                              ("workflow automation tools (Zapier, n8n, Make)", "low-code / no-code"),
                              ("HRIS (Workday HCM, Dayforce, SuccessFactors)", "ERP (SAP/Oracle/Workday)")]:
        assert _is_tool(product), product
        assert product in taxonomy.TOOL_TYPES, product
        assert taxonomy.RELATED[product] == platform
        assert taxonomy.category(platform), platform
    for name in ["Linear", "Notion", "Slack"]:
        assert _is_tool(name) and name in taxonomy.TOOL_TYPES, name
