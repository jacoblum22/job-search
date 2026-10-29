"""Skills taxonomy: ~130 skills, each with synonyms and false-match guards.

Ported from the project's skills analysis (skills/taxonomy.py, Oct 17 2026).
Each entry is (category, display name, regex); regexes are case-insensitive
unless they start with ``(?-i)``. This list is the matcher for the tailoring
pipeline; it grows from the monthly public-list cross-check
(scripts/skills_crosscheck.py) and the unknown-terms log.
"""

from __future__ import annotations

import re
from functools import lru_cache

from src.tailor import wording

# Business systems that, listed next to a bare "Oracle", mean Oracle's ERP or project software.
_BUSINESS_SYSTEMS = r"\b(?:sap|erp|workday|primavera|peoplesoft|netsuite|jd edwards|ecosys)\b"

T = [
# Languages
("Languages","SQL",r"\bsql\b|t-sql|pl/sql|\bmysql\b|postgres|sql server|\bsqlite\b"
 # Bare "Oracle" is the database; Oracle's ERP products go to the ERP entry below.
 r"|\boracle\b(?! ?(?:erp|fusion|e-?business|netsuite|cloud erp|cloud applications|financials|hcm))"
 # ...unless it sits in a list of business systems ("Primavera P6, Oracle, SAP"): then it's ERP.
 r"(?![^.;\n]{0,80}" + _BUSINESS_SYSTEMS + r")(?<!sap, oracle)(?<!sap or oracle)(?<!sap/oracle)"),
("Languages","Python",r"\bpython\b"),
("Languages","R",r"(?-i)\bR\b(?![&-])(?!\s?&)|\bRStudio\b|\btidyverse\b"),
("Languages","Java",r"\bjava\b(?!script)"),
("Languages","JavaScript",r"javascript"),
# Node.js is a server runtime: front-end JavaScript or TypeScript doesn't show it. RELATED links it to JavaScript.
("Libraries","Node.js",r"\bnode\.?js\b|\bnodejs\b"),
("Languages","TypeScript",r"typescript"),
("Languages","C#/.NET",r"c#|(?<!\w)\.net\b|\b(?:asp|vb)\.net\b"),
("Languages","C/C++",r"(?-i)[Cc]\+\+|\bC\b(?!#|\+)(?=[,/ ]+(?:C\+\+|and|or|Java|Python))"),
("Languages","Go",r"(?-i)\b(Golang|Go)\b(?=[,/) ]+(?:and|or|Java|Python|Rust|Kotlin|C\+\+|Scala))|\b[Gg]olang\b"
 r"|(?<=, )Go\b|(?<=or )Go\b|(?<=and )Go\b"),
("Languages","Scala",r"\bscala\b"),
("Languages","SAS",r"(?-i)\bSAS\b"),
("Languages","SPSS",r"\bspss\b"),
("Languages","Stata",r"\bstata\b"),
("Languages","MATLAB",r"\bmatlab\b"),
# A capitalised word after "Julia" is a surname ("Julia Rubin"), not the language.
("Languages","Julia",r"(?-i)\bJulia\b(?!\s+[A-Z])"),
("Languages","Perl",r"\bperl\b"),
("Languages","Ruby",r"\bruby\b"),
("Languages","PowerShell",r"powershell"),
("Languages","VBA",r"\bvba\b|\bmacros?\b"),
("Languages","Bash/Shell",r"\bbash\b|shell script"),
("Cloud & DevOps","Linux/Unix",r"\blinux\b|\bunix\b"),
("Languages","Kotlin/Swift",r"\bkotlin\b|\bswift\b"),
("Languages","Rust",r"\brust\b"),
("Languages","HTML/CSS",r"(?<![./-])\bhtml\b|(?<![./-])\bcss\b"),  # not a file name ("about-cibc.html")
("Languages","PHP",r"\bphp\b"),
("Languages","kdb+/q",r"\bkdb\b"),
# Salesforce's query language. RELATED links it to Salesforce.
("Languages","SOQL",r"\bsoql\b"),
# Python/data libs
("Libraries","pandas",r"\bpandas\b"),
("Libraries","NumPy",r"\bnumpy\b"),
("Libraries","scikit-learn",r"scikit|sklearn"),
("Libraries","PyTorch",r"pytorch|\btorch\b"),
("Libraries","TensorFlow/Keras",r"tensorflow|\bkeras\b"),
("Libraries","XGBoost/LightGBM",r"xgboost|lightgbm|catboost|gradient boost"),
("Libraries","Hugging Face",r"hugging ?face|transformers library"),
("Libraries","JAX",r"(?-i)\b(?:JAX|Jax)\b"),
("Libraries","spaCy / NLTK",r"\b(?:med)?spacy\b|\bnltk\b"),
("Libraries","vLLM",r"\bvllm\b"),
("Libraries","LangChain/LlamaIndex",r"langchain|llamaindex|langgraph"),
("Libraries","Jupyter",r"jupyter|notebooks?\b"),
("Libraries","matplotlib/seaborn/plotly",r"matplotlib|seaborn|plotly|ggplot"),
("Libraries","React",r"\breact\b"),
("Libraries","Angular",r"(?-i)\bAngular(?:JS)?\b"),
("Libraries","Vue",r"(?-i)\bVue(?:\.js)?\b"),
("Libraries","Spring",r"(?-i)\bSpring(?: Boot)?\b(?! (?:term|semester|break|20\d\d))"),
("Libraries","FastAPI/Flask/Django",r"fastapi|\bflask\b|django"),
# Capitalised "Rails" is the framework; "payment rails" is banking.
("Libraries","Ruby on Rails",r"ruby on rails|(?-i:(?<!Payment )\bRails\b)"),
("Libraries","ORM (Hibernate / SQLAlchemy)",r"(?-i)\bORMs?\b|\bHibernate\b|\bSQLAlchemy\b|\bJPA2?\b"),
("Libraries","Three.js / WebGL",r"three\.js|webgl|babylon\.?js|react three fiber"),
# Unity is also a company ("Life at Unity"): only the engine, or Unity in a list of tools.
("Libraries","Unity / Unreal Engine",r"unreal engine|(?-i:\bUnity ?(?:3D|Engine)\b|(?<=, )Unity\b(?=,| or\b| and\b)|(?<=such as )Unity\b)"),
# BI / analytics
# Capitalised "Excel" is the tool; lowercase "excel" is usually the verb ("our people can excel").
# A sentence that opens "Excel at" / "Excel in" is the verb too.
("BI & analytics","Excel",r"(?-i)(?<![.!?•\-] )(?<!^)(?<!\n)\bExcel\b|\bExcel\b(?! (?:at|in)\b)|\bEXCEL\b|(?i:\b(?:ms|microsoft|advanced|intermediate) excel\b|\bexcel (?:skills|spreadsheets?|formulas?|macros|vba|models?)\b"
 r"|spreadsheets?|pivot ?tables?|v-?look ?ups?|xlookup|index.match|conditional formatting)"),
("BI & analytics","Power BI",r"power ?bi|\bdax\b"),
("BI & analytics","Tableau",r"tableau"),
# Looker (the enterprise BI platform, LookML) and Looker Studio (formerly Data Studio) are
# different products.
("BI & analytics","Looker",r"\blooker\b(?![\s-]+studio)|\blookml\b"),
("BI & analytics","Looker Studio",r"looker[\s-]+studio|data studio"),
("BI & analytics","Qlik",r"\bqlik"),
("BI & analytics","Google Analytics",r"google analytics|\bga4\b"),
("BI & analytics","dashboards",r"dashboard"),
("BI & analytics","data visualization",r"visuali[sz]"),
("BI & analytics","reporting",r"\breporting\b|\breports\b|\bbuild(?:ing)? reports?"),
# "Econometrics" is the method, not metrics; investment performance measurement has its own entry.
("BI & analytics","KPIs/metrics",r"\bkpis?\b|key performance|\bmetrics|(?<!investment )performance measure"),
("BI & analytics","A/B testing / experimentation",r"a/b test|experiment(?:ation|al design| design)|\bab test|online experiment|sample size (?:estimation|calculation)|power analysis|statistical power"),
("BI & analytics","Power Query",r"power query"),
("BI & analytics","Power Automate",r"power automate"),
("BI & analytics","Power Apps",r"power apps"),
("BI & analytics","Microsoft Power Platform",r"power platform"),
("BI & analytics","Dataverse",r"dataverse"),
("BI & analytics","Superset",r"\bsuperset\b"),
("BI & analytics","Metabase",r"metabase"),
("BI & analytics","Sigma",r"(?-i)(?<!Six )(?<!six )(?<!6 )\bSigma\b(?! ?(?:Xi|Chi))|sigma computing"),
("BI & analytics","MicroStrategy",r"microstrategy"),
("BI & analytics","Cognos",r"cognos"),
("BI & analytics","Amplitude / Mixpanel",r"(?-i)\bAmplitude\b|\b[Mm]ixpanel\b"),
("BI & analytics","Hex",r"(?-i)\bHex\b(?! (?:code|codes|colou?rs?|values?|keys?))"),
("BI & analytics","Statsig",r"statsig"),
# The discipline, not a tool. Bare "BI" counts only when it isn't part of "Power BI" or Databricks' "AI/BI".
("BI & analytics","business intelligence",r"business intelligence|(?-i:(?<!Power )(?<!AI/)\bBI\b)"),
("BI & analytics","data analysis",r"\bdata analysis\b|exploratory data analys"),
# Product telemetry only: hardware and ops telemetry ("telemetry protocols", "logs, telemetry") is monitoring.
("BI & analytics","event tracking / instrumentation",r"tracking plans?|measurement plans?|(?:event|product|analytics) (?:tracking|instrumentation)|tracking and instrumentation|tag management"
 r"|(?:usage|adoption|product|event) (?:and )?telemetry|telemetry (?:data|validation|events)"),
("BI & analytics","self-serve analytics",r"self.serv(?:e|ice) (?:analytics|bi|reporting|dashboards?|data|insights|tools)"),
# Data engineering / warehouse
("Data platforms","Snowflake",r"snowflake"),
("Data platforms","Databricks",r"databricks|data bricks"),
("Data platforms","BigQuery",r"bigquery|big query"),
("Data platforms","Redshift",r"redshift"),
("Data platforms","Spark/PySpark",r"\bspark\b|pyspark"),
("Data platforms","dbt",r"\bdbt\b"),
("Data platforms","Airflow",r"airflow"),
("Data platforms","Dagster",r"dagster"),
("Data platforms","Alteryx",r"alteryx"),
("Data platforms","Prefect",r"(?-i)\bPrefect\b"),
("Data platforms","Fivetran",r"fivetran"),
("Data platforms","Flink",r"\bflink\b"),
("Data platforms","Elasticsearch",r"elasticsearch|opensearch"),
("Data platforms","vector databases",r"vector (?:database|db|store)s?|pinecone|weaviate|pgvector"),
("Data platforms","Kafka",r"\bkafka\b"),
("Data platforms","Confluent",r"\bconfluent\b"),
("Data platforms","Hadoop/Hive",r"hadoop|\bhive\b|\bhbase\b|mapreduce"),
("Data platforms","ETL/ELT",r"\betl\b|\belt\b|extract, transform"),
("Data platforms","data pipelines",r"data pipelines?|etl pipelines?|ml pipelines?|pipelines? (?:for|that) data|batch processing|workflow orchestration"),
("Data platforms","data warehouse",r"data warehous|warehouse|data lake|lakehouse"),
("Data platforms","data modeling",r"data model|dimensional model|star schema|fact (?:and|&) dimension|(?:fact|dimension) tables?|slowly changing dimension"),
("Data platforms","data quality / validation",r"data quality|data integrity|data validation|data cleans|data cleaning"
 r"|\bdata qa\b|\bvalidated\b[^.;]{0,100}\bdata\b"),
("Data platforms","data governance",r"data governance|data stewardship|metadata|data classification"),
# Relational databases (PostgreSQL, MySQL, SQL Server, SQLite) stay under SQL: SQL skill carries
# over between them. NoSQL databases each work differently, so each is its own skill (Jake, Oct 18 2026).
("Data platforms","NoSQL",r"\bnosql\b"),
("Data platforms","MongoDB",r"mongodb|\bmongo\b"),
("Data platforms","DynamoDB",r"dynamodb"),
("Data platforms","Cassandra",r"cassandra"),
("Data platforms","Cosmos DB",r"cosmos ?db"),
("Data platforms","Redis",r"\bredis\b"),
("Data platforms","Supabase",r"supabase"),
("Data platforms","Presto/Trino",r"\bpresto\b|\btrino\b"),
("Data platforms","Delta Lake",r"delta lake"),
# "The tip of the iceberg" is the idiom, not the table format.
("Data platforms","Apache Iceberg",r"(?<!tip of the )\biceberg\b"),
("Data platforms","Unity Catalog",r"unity catalog"),
("Data platforms","Snowflake Cortex",r"snowflake cortex|\bcortex (?:analyst|agents?|search|aisql|ai)\b|snowflake intelligence"),
("Data platforms","Snowpark",r"snowpark"),
("Data platforms","Dataform",r"\bdataform\b"),
("Data platforms","SQLMesh",r"sqlmesh"),
("Data platforms","VisualCron",r"visualcron"),
("Data platforms","Dataiku",r"dataiku"),
# Lowercase "rest" is the word ("the rest of", "rest and recharge"); the API style is written REST.
# Named API products (LLM APIs, API Gateway, Graph API) go to their own entries.
("Data platforms","APIs / REST",r"(?<!llm )(?<!graph )\bapis?\b(?! gateway)|\brestful\b|(?-i:\bREST\b)|\bwebhooks?\b"),
("Data platforms","Microsoft Fabric / Azure Synapse / ADF",r"microsoft fabric|\bfabric\b(?= data| lakehouse)|synapse|data factory"),
("Data platforms","SSIS/SSRS",r"\bssis\b|\bssrs\b|\bssas\b"),
# Cloud & devops
# A platform's own products get their own entries: S3 experience doesn't show SageMaker.
# RELATED links each product to its platform ("AWS S3" in the vault matches both).
("Cloud & DevOps","AWS",r"\baws\b|amazon web services"),
("Cloud & DevOps","AWS S3",r"\bs3\b"),
("Cloud & DevOps","AWS Lambda",r"\blambda\b(?! ?(?:function|expression|calculus))|aws lambda"),
("Cloud & DevOps","Amazon SageMaker",r"sagemaker"),
("Cloud & DevOps","Amazon Bedrock",r"bedrock"),
("Cloud & DevOps","Amazon Kinesis",r"kinesis|firehose"),
("Cloud & DevOps","AWS Glue",r"(?-i)\b(?:AWS )?Glue\b"),
("Cloud & DevOps","Amazon Athena",r"(?-i)\bAthena\b"),
("Cloud & DevOps","Amazon EMR",r"(?-i)\bEMR\b(?! (?:system|record|data))"),
("Cloud & DevOps","Amazon EC2",r"\bec2\b"),
("Cloud & DevOps","Amazon SQS / SNS",r"(?-i)\bSQS\b|\bSNS\b"),
# Bare "ECS" only inside a comma list of services: "log schemas such as ECS" is Elastic Common Schema.
("Cloud & DevOps","Amazon ECS",r"(?-i)(?:AWS|Amazon) ECS\b|(?<=, )ECS\b(?=,)|[Ee]lastic [Cc]ontainer [Ss]ervice"),
("Cloud & DevOps","AWS CloudFormation",r"cloudformation"),
("Cloud & DevOps","AWS API Gateway",r"api gateway"),
("Cloud & DevOps","Amazon CloudWatch",r"cloudwatch"),
("Cloud & DevOps","Amazon RDS",r"(?-i)\bRDS\b|[Rr]elational [Dd]atabase [Ss]ervice"),
("Cloud & DevOps","Google Cloud Composer",r"cloud composer"),
("Cloud & DevOps","Datadog",r"datadog"),
("Cloud & DevOps","Grafana",r"grafana"),
("Cloud & DevOps","Prometheus",r"(?-i)\bPrometheus\b"),
("Cloud & DevOps","ELK Stack",r"elk stack|(?-i:\bELK\b)"),
("Cloud & DevOps","Ansible / Puppet",r"\bansible\b|(?-i:\bPuppet\b)"),
("Cloud & DevOps","Azure",r"\bazure\b"),
("Cloud & DevOps","Azure Machine Learning",r"azure machine learning|azure ml\b"),
("Cloud & DevOps","Azure OpenAI",r"azure openai"),
("Cloud & DevOps","Microsoft Graph API",r"microsoft graph|\bgraph api\b"),
# An "enterprise service bus" can be any vendor's.
("Cloud & DevOps","Azure integration services (Logic Apps / Service Bus / Event Grid)",r"azure integration services|logic apps|(?<!enterprise )service bus|event grid|azure api management"),
("Cloud & DevOps","GCP",r"\bgcp\b|google cloud(?! oauth)"),
("Cloud & DevOps","Vertex AI",r"vertex ai"),
# Software containers; shipping and storage containers are not.
("Cloud & DevOps","Docker",r"docker|containeri[sz]|(?<!shipping )(?<!storage )(?<!cargo )\bcontainers?\b"),
("Cloud & DevOps","Kubernetes",r"kubernetes|\bk8s\b"),
("Cloud & DevOps","CI/CD",r"ci/cd|continuous integration|continuous deliver|github actions|jenkins|azure devops|azure pipelines"),
("Cloud & DevOps","Git",r"\bgit\b|github(?! copilot)|gitlab|bitbucket|version control|source control"),
("Cloud & DevOps","Terraform/IaC",r"terraform|infrastructure as code"),
("Cloud & DevOps","MLOps",r"mlops|llmops|model deployment|deploy(?:ing)? models|model monitoring|(?:model|data|concept) drift|retrain(?:ing)? models?|model retraining"
 r"|experiment tracking|model registr|feature stores?"),
("Cloud & DevOps","MLflow",r"mlflow"),
# Regression testing is re-running tests after a change, not statistical regression.
("Cloud & DevOps","testing (unit/automated)",r"unit test|automated test|test automation|pytest|\btdd\b|test.driven|(?-i:\bBDD\b)|behaviou?r.driven"
 r"|regression test|integration test|end.to.end test"),
("Cloud & DevOps","microservices",r"microservice"),
("Cloud & DevOps","distributed systems",r"distributed system"),
("Cloud & DevOps","software architecture / system design",r"design patterns|system design|software (?:architecture|design)|(?:service|component)-based architectures?|architectural patterns"),
("Cloud & DevOps","event-driven architecture",r"event.driven"),
("Cloud & DevOps","site reliability engineering (SRE)",r"site reliability|(?-i:\bSRE\b)"),
("Cloud & DevOps","open-source contribution",r"open.source contributions?|contribut\w* (?:to|back to) open.source|open.source (?:projects?|community|maintainers?)"),
# ML / stats methods
("ML & statistics","machine learning",r"machine learning|\bml\b|(?:un)?supervised learning|tree.based models?|random forests?|decision trees?"),
# The field. A "Data Science team" is the employer's org chart.
("ML & statistics","data science",r"data science(?! (?:team|department|group|org|function|leaders?|managers?)\b)"),
("ML & statistics","AI (any mention)",r"\bai\b|artificial intelligence"),
# "The highest probability of reaching $1B" is a company boast, not the topic.
("ML & statistics","statistics",r"statistic|\bprobability\b(?! (?:of|that|to)\b)"),
("ML & statistics","descriptive statistics / correlation",r"descriptive statistic|standard deviation|\bmedian\b(?! (?:salary|pay|base|compensation|income))"
 r"|\bcorrelations?\b(?! rules)|\bquartiles?\b|trendline|trend analys"),
("ML & statistics","predictive modeling",r"predictive|forecast"),
("ML & statistics","regression",r"regression(?! test| suites?)(?!,? (?:acceptance|integration|system|unit|smoke)\b)"),
# Data classification is governance (sensitivity labels), not the ML task.
("ML & statistics","classification",r"(?<!data )classification|classifier"),
# Kubernetes, Hadoop and "clustered data processing" clusters are compute, not the method.
("ML & statistics","clustering/segmentation",r"clustering(?! (?:and|or) (?:high availability|replication|failover))|cluster analysis|k.means|segmentation"),
("ML & statistics","deep learning / neural nets",r"deep learning|neural net|\bcnns?\b|convolutional|autoencoders?|transformer(?: |-based )(?:models?|architectures?)|transformer-based|vision transformers?|\brnns?\b|\blstms?\b"),
("ML & statistics","NLP",r"\bnlp\b|natural language"),
# Positional embeddings (RoPE) are a transformer part, not vector embeddings for search or RAG.
("ML & statistics","embeddings",r"(?<!position )(?<!positional )\bembeddings?\b"),
("ML & statistics","LLMs / generative AI",r"llm apis?|\bllms?\b|large language|generative ai|\bgenai\b|\bgpt\b|prompt engineering"),
# RAG is its own technique: other LLM work doesn't show it. RELATED links it to LLMs.
("ML & statistics","RAG (retrieval-augmented generation)",r"(?-i:\bRAG\b)|retrieval.augmented"),
("ML & statistics","computer vision",r"computer vision|image processing|image and video processing|video processing|object (?:detection|tracking|recognition)|image segmentation"),
("ML & statistics","time series",r"time.series"),
("ML & statistics","hypothesis testing / inference",r"hypothesis|statistical inference|significance test|causal|\bt-tests?\b|chi.squared?|\banova\b"
 r"|quasi.experiment|difference.in.differences|propensity score"),
("ML & statistics","feature engineering",r"feature engineering"),
("ML & statistics","model evaluation/validation",r"model (?:evaluation|validation|performance)|cross.validation|offline evaluations?"),
# Query, performance and process optimisation are tuning work, not operations research.
("ML & statistics","optimization / OR",r"(?<!query )(?<!performance )(?<!sql )(?<!process )(?<!engine )(?<!code )(?<!-specific )(?<!inference )optimi[sz]ation|operations research|linear programming|integer programming"),
("ML & statistics","recommendation systems",r"recommend(?:er|ation) (?:system|engine|model)|recommenders?\b|next best action|ranking models?"),
# Churn is a business metric; only survival wording is the method.
("ML & statistics","survival analysis",r"survival analysis|survival models?|time.to.event|hazard models?"),
("ML & statistics","Bayesian methods",r"bayesian"),
("ML & statistics","mathematics (linear algebra, calculus)",r"linear algebra|calculus|mathematic"),
("ML & statistics","econometrics",r"econometric"),
("ML & statistics","control theory",r"control theory"),
("ML & statistics","data mining",r"data mining"),
("ML & statistics","quantitative analysis",r"quantitative"),
# Business tools
("Business tools","Salesforce/CRM",r"salesforce|\bcrm\b|hubspot|dynamics 365"),
# ERP only on ERP product wording: a sponsor name ("WiDS × SAP datathon") or a Workday careers
# site is not ERP experience.
("Business tools","ERP (SAP/Oracle/Workday)",r"\berp\b|(?<!× )(?<!\bx )\bsap\b(?! ?(?:datathon|hackathon|challenge|customer|competition))|s/4 ?hana"
 r"|oracle ?(?:erp|fusion|e-?business|netsuite|cloud erp|financials|hcm)|netsuite"
 r"|\boracle\b(?=[^.;\n]{0,80}" + _BUSINESS_SYSTEMS + r")|(?<=sap, )oracle|(?<=sap or )oracle|(?<=sap/)oracle"
 r"|workday (?:hcm|financials|adaptive|prism)"),
("Business tools","Jira/Confluence",r"\bjira\b|confluence(?! cloud)"),
("Business tools","Visio / diagramming",r"\bvisio\b|lucidchart|draw\.io|\bmiro\b"),
# A bare "Access" or "Word" only counts as the Microsoft tool when it is the whole term
# (a posting's tools list), never as a word inside a sentence ("access tokens").
("Business tools","Microsoft Access",r"microsoft access|ms access|access database|^access$"),
# "Word" and "Outlook" are capitalised and sit in a list of Office apps; the plain words aren't tools.
("Business tools","Microsoft Word",r"(?-i)[Mm]icrosoft [Ww]ord|MS Word|^[Ww]ord$|\bWord\b(?=[^.\n]{0,40}\b(?:Excel|PowerPoint|Outlook|OneNote|Access)\b)"
 r"|(?<=Excel, )Word\b|(?<=Excel and )Word\b|(?<=Excel & )Word\b|(?<=Outlook, )Word\b|(?<=PowerPoint, )Word\b"),
("Business tools","Microsoft Outlook",r"(?-i)[Mm]icrosoft Outlook|MS Outlook|^Outlook$|\bOutlook\b(?=[^.\n]{0,40}\b(?:Excel|PowerPoint|Word|OneNote|Teams)\b)"
 r"|(?<=Excel, )Outlook\b|(?<=Word, )Outlook\b|(?<=PowerPoint, )Outlook\b|(?<=\()Outlook\b"),
("Business tools","Microsoft PowerPoint",r"powerpoint"),
("Business tools","Microsoft Teams",r"microsoft teams|ms teams|(?-i:(?<=SharePoint and )Teams\b)"),
("Business tools","Google Sheets / Workspace",r"google sheets|google workspace|g suite"),
("Business tools","ServiceNow",r"servicenow"),
("Business tools","Stripe",r"(?-i)\bStripe\b"),
("Business tools","test management (TestRail, qTest, Xray)",r"testrail|\bqtest\b|(?-i:\bXray\b)"),
("Business tools","project controls (Primavera P6, EcoSys)",r"primavera|\becosys\b"),
# AI assistants and model APIs: products, each its own skill.
("AI tools","Claude / Claude Code",r"\bclaude\b|\banthropic\b"),
("AI tools","ChatGPT",r"chatgpt"),
("AI tools","OpenAI API",r"\bopenai\b(?! chatgpt)"),
("AI tools","GitHub Copilot",r"github copilot"),
("AI tools","Microsoft Copilot",r"microsoft copilot|m365 copilot|microsoft 365 copilot|copilot studio"),
("AI tools","Cursor",r"(?-i)\bCursor\b"),
("AI tools","Codex",r"\bcodex\b"),
("AI tools","Gemini",r"(?-i)\bGemini\b"),
# The practice of coding with AI assistants or agents, whichever the tool.
("AI tools","AI-assisted coding",r"ai.assisted (?:coding|development|programming|software)|ai (?:coding|development|pair.programming) (?:tools|assistants?)|coding (?:agents?|assistants?)|agentic coding|code copilots|coding.agent"),
("Business tools","Microsoft Office",r"microsoft office|ms office|office 365|microsoft 365|word, excel|powerpoint"),
("Business tools","Agile/Scrum",r"\bagile\b|scrum|kanban|sprint"),
("Business tools","project management",r"project management|project manager|pmp|pmbok|\bcapm\b"),
("Business tools","change management",r"change management"),
("Business tools","market research",r"market research|market sizing|competitive (?:analysis|landscape|intelligence)"),
("Business tools","robotic process automation (RPA)",r"robotic process automation|(?-i:\bRPA\b)|uipath|automation anywhere|blue prism"),
("Business tools","low-code / no-code",r"low.code|\bno-code\b"),
("Business tools","Anaplan",r"anaplan"),
("Business tools","Acumatica",r"acumatica"),
("Business tools","Marketo",r"marketo"),
("Business tools","Agentforce",r"agentforce"),
# The terminal and data, not the company: "At Bloomberg, we..." isn't a skill.
("Business tools","Bloomberg",r"bloomberg (?:terminal|bql|api|data license)|(?-i:(?<!At )(?<!at )\bBloomberg\b(?=[,)]| (?:and|or|is (?:desired|an asset|required|preferred))\b))"
 r"|(?<=, )bloomberg\b|(?<=and )bloomberg\b"),
("Business tools","GIS",r"\bgis\b|arcgis|geospatial"),
("BI & analytics","Amazon QuickSight",r"quicksight"),
("Business tools","SharePoint",r"sharepoint"),
("Data platforms","GraphQL",r"graphql"),
("Data platforms","JSON",r"\bjson\b"),
("ML & statistics","AI agents / agentic AI / MCP",r"agentic|ai agents?|\bmcp\b|model context protocol|langgraph|tool.calling|function.calling|\btool.use\b"),
("Cloud & DevOps","SDLC",r"\bsdlc\b|software development life ?cycle"),
("Cloud & DevOps","networking (TCP/IP)",r"tcp/ip|\btcp\b|\budp\b|networking protocols"),
("Cloud & DevOps","QA / UAT",r"\buat\b|user acceptance|quality assurance|acceptance testing|manual testing|exploratory testing|test (?:cases|plans)\b"
 r"|\b(?:acceptance|exploratory)\b[^.\n]{0,50}\btests\b"),
# Data work and engineering practice (Oct 19 2026, from an audit of the 73 A-tier postings).
("Data platforms","data transformation / preparation",r"data (?:transformations?|preparation|prep|wrangling|manipulation|munging)|transform(?:s|ed|ing)? (?!(?:the way|how) )(?:[\w-]+ ){0,2}data\b|prepar(?:e|ing) data|\bwrangl"),
# Combining sources is integration work ("multi-source data", "combining data from several sources").
("Data platforms","data integration",r"data integration|system integrations?|integrat(?:e|ing) data|integrations? (?:between|across) (?:systems|platforms|tools)|(?:third.party|enterprise|platform) integrations?|integrat(?:e|ed|es|ing|ion) (?:of )?(?:the )?(?:third.party|external|outside|vendor) (?:\S+ ){0,3}?(?:data|sources?|systems|feeds)|multi.source|combin(?:e|ed|ing) (?:data from )?(?:multiple|several|different|many) (?:data )?sources"),
("Data platforms","secure coding / OWASP",r"secure coding|secure (?:software|code) (?:development|practices)|\bowasp\b"),
("Data platforms","data privacy / security",r"data privacy|privacy (?:laws|legislation|regulations|requirements|by design)|\bpii\b|personally identifiable|\bgdpr\b|\bccpa\b|\bpipeda\b|\bfoippa\b|\bhipaa\b|data security|data protection|\bencryption\b|access controls?|role.based access|row.level security|information security|cyber.?security|secrets? management|data masking|anonymi[sz]|pseudonymi[sz]|de-identif"),
("Data platforms","query / performance tuning",r"query (?:optimi[sz]ation|performance|tuning)|optimi[sz](?:e|ing) (?:sql|queries|query)|performance (?:tuning|optimi[sz]ation)|(?:sql|query|database) tuning|tun(?:e|ing) (?:sql|queries)|(?:efficient|cost.effective) (?:sql|queries)|(?:sql|queries|query) (?:\w+ )?efficient|query costs?"),
("Data platforms","data lineage / catalog",r"data lineage|\blineage\b|data catalog(?:ue)?s?|data dictionar|metadata management"),
("Data platforms","semantic layer / metrics layer",r"semantic (?:layers?|models?|views)|governed metrics|metrics? (?:layer|store|registry)|metric (?:definitions|governance)"),
("Data platforms","data reconciliation",r"data reconciliation|reconcil(?:e|ing) (?:data|numbers|figures|across)"),
("Data platforms","relational databases / database design",r"(?<!non-)(?<!non)relational (?:databases?|tables?)|primary (?:and|&|/) foreign keys?|foreign keys?|database design|database (?:management|development|administration)|\brdbms\b|schema design"),
("Data platforms","real-time / streaming data",r"real.time (?:data|analytics|processing|pipelines?|streaming|ingestion)|stream processing|streaming (?:data|pipelines?|analytics)"),
("Languages","SQL window functions / CTEs",r"window functions?|\bctes?\b|common table expressions?"),
("Languages","SQL stored procedures",r"stored procedures?|stored procs?\b"),
("Languages","concurrency / multithreading",r"multi.?thread|concurren(?:cy|t programming)|parallel programming"),
("Languages","object-oriented programming",r"object.oriented|(?-i:\bOOP\b)|\boo design"),
# The CS fundamentals. "Create and populate data structures using schema definition languages" is data modelling.
("Languages","data structures / algorithms",r"data structures(?=[^.\n]{0,40}algorithm)|algorithms?[^.\n]{0,30}data structures"
# The whole term "data structures" (a posting's skills list) is the CS topic too.
 r"|(?:knowledge|foundation|understanding|fundamentals) (?:of |in )?data structures|^data structures$"),
("Data platforms","data engineering",r"data engineering"),
("Data platforms","analytics engineering",r"analytics engineer"),
("Data platforms","data migration",r"data migrations?|migrat(?:e|ing|ion of) (?:the )?data\b"),
("Data platforms","data mapping",r"data mapping|source.to.target|field mapping"),
("Data platforms","OLAP / cubes",r"\bolap\b|\bmdx\b|multidimensional (?:databases?|cubes?|models?)"),
("Data platforms","big data",r"big data"),
("Data platforms","knowledge graphs / ontologies",r"knowledge graphs?|ontolog|graph databases?|\bneo4j\b|(?-i:\bRDF\b)"),
("Languages","web development (full-stack)",r"full.?stack|front.?end|back.?end|web (?:applications?|apps?|development|developer)|server.side (?:programming|development|frameworks?|languages?|rendering)"),
("Cloud & DevOps","debugging / troubleshooting",r"debug|troubleshoot"),
("Cloud & DevOps","code review",r"code reviews?|review(?:ing)? (?:code|pull requests|prs)\b|pull requests?"),
("Cloud & DevOps","pipeline monitoring / alerting",r"\balerting\b|observability|monitor(?:ing)? (?:of )?(?:data )?(?:pipelines?|jobs|loads|dags|data quality)"),
("Cloud & DevOps","incident response / on-call",r"\bon.call\b|incident (?:response|management)|production support|data incidents?"),
("Cloud & DevOps","Playwright",r"playwright"),
("Cloud & DevOps","Selenium",r"selenium"),
("Cloud & DevOps","Cypress",r"(?-i)\bCypress\b"),
("Cloud & DevOps","Postman",r"(?-i)\bPostman\b"),
("Cloud & DevOps","JMeter / k6",r"jmeter|(?-i:\bk6\b)"),
("Cloud & DevOps","Jest / Vitest",r"(?-i)\bJest\b|\b[Vv]itest\b"),
("Cloud & DevOps","performance / load testing",r"performance test(?:s|ing)?\b|load test(?:s|ing)?\b"),
("Cloud & DevOps","threat modeling / penetration testing",r"threat model|penetration test|\bpen ?test"),
# The practice. "Azure DevOps" is the CI/CD product (above).
("Cloud & DevOps","DevOps",r"(?<!azure )\bdevops\b"),
("Cloud & DevOps","serverless",r"serverless"),
("Cloud & DevOps","IAM (identity and access management)",r"(?-i:\bIAM\b)|identity and access management"),
("Cloud & DevOps","GPU computing / CUDA",r"\bcuda\b|\bgpus?\b|\btpus?\b"),
# Google Cloud's data products, each its own skill (as with AWS).
("Cloud & DevOps","Google Cloud Storage",r"google cloud storage|(?-i:\bGCS\b)"),
("Cloud & DevOps","Google Cloud Dataflow / Apache Beam",r"(?-i:\bDataflow\b)|cloud dataflow|apache beam"),
("Cloud & DevOps","Google Cloud Pub/Sub",r"pub/sub|\bpubsub\b"),
("BI & analytics","root cause analysis",r"root.cause"),
("BI & analytics","data-driven decision-making",r"data.driven (?:decisions?|decision.making|insights?|approach|culture|recommendations)|evidence.based (?:decisions?|decision.making)|inform(?:s|ed|ing)? (?:business |key |strategic )?decisions|decision support"),
# A marketing or sales funnel is demand generation (below), not in-product funnels.
("BI & analytics","product analytics (funnels / cohorts / LTV)",r"(?<!marketing )(?<!sales )(?<!lead )\bfunnels?\b|cohort|lifetime value|(?-i:\b(?:LTV|CLV|CLTV)\b)|feature adoption|product analytics|(?:analy[sz]e|map|mapping) (?:\w+ ){0,3}user journeys?|user journey (?:analysis|mapping)"),
("BI & analytics","churn / retention analysis",r"\bchurn|customer retention|retention (?:analysis|rates?|modell?ing)"),
("BI & analytics","SaaS metrics (ARR / MRR / NRR)",r"(?-i:\b(?:ARR|MRR|NRR|GRR)\b)|recurring revenue|net (?:revenue|dollar) retention|saas metrics"),
("BI & analytics","marketing analytics / attribution",r"marketing analytics|(?:marketing|multi.?touch|campaign|channel) attribution|attribution model|marketing mix model|(?-i:\bUTMs?\b)|(?-i:\bCAC\b|\bROAS\b)|customer acquisition costs?|return on ad spend|performance marketing (?:metrics|teams?|campaigns?|channels?|data|analytics)"),
("BI & analytics","report / process automation",r"automat(?:e|ed|ing|ion of) (?:the |our )?(?:recurring |manual |routine )?(?:reports?|reporting|processes|workflows?|tasks|data (?:loads|ingest|ingestion|collection))|(?:report|reporting|process|workflow) automation|automat(?:e|es|ed|ing) (?:repetitive|manual)\b"),
("ML & statistics","anomaly detection",r"anomaly detection|detect(?:ing)? anomalies|outlier detection"),
("ML & statistics","model interpretability / explainability",r"interpretab|explainab|(?-i:\bSHAP\b)"),
("ML & statistics","responsible AI / AI ethics",r"responsible ai|ai ethics|ethical ai|ethics of ai|model governance|ai governance|bias mitigation"),
("ML & statistics","LLM / AI evaluation",r"llm evaluation|evaluat(?:e|ing|ion of) (?:llms?|model outputs?|ai outputs?|agents?|ai systems)|llm.as.a.judge|llm judges?|\bevals\b|eval(?:uation)? harness(?:es)?"),
("ML & statistics","prompt engineering",r"prompt (?:engineering|design|development|evaluation|optimi[sz]ation|templates?)|structured prompting|\bprompting\b"),
("ML & statistics","unstructured data / OCR",r"unstructured data|(?-i:\bOCR\b)|document ai|document (?:understanding|extraction|parsing)"),
("ML & statistics","scenario analysis / simulation",r"scenario (?:analysis|modell?ing|planning)|what.if (?:analysis|scenarios?)|stress test|monte carlo|simulation (?:models?|modell?ing|studies)|digital twins?"),
# Model fine-tuning, not tuning a process. Uppercase LoRA only: LoRa is the IoT radio.
("ML & statistics","fine-tuning (LoRA / PEFT)",r"\bfine.tun(?:ing|e|ed)\b(?! (?:our |the |your |their |my )?(?:process|processes|workflows?|strateg|operations|skills?|abilities))"
 r"|(?-i:\bQ?LoRA\b)|\bpeft\b|parameter.efficient"),
("ML & statistics","named entity recognition / entity resolution",r"named entity|entity (?:resolution|linking|extraction|recognition)|(?-i:\bNER\b)"),
("ML & statistics","model serving / inference optimization",r"model serving|serving models|inference (?:optimi[sz]ation|serving|latency|endpoints?)|quantization|(?:model|knowledge) distillation"),
("ML & statistics","search / information retrieval",r"information retrieval|retrieval systems|re-?rank(?:ing|ers?)\b|hybrid search|vector search|semantic search|search relevance|retrieval.based"),
("ML & statistics","text-to-SQL / conversational analytics",r"text.to.sql|natural language (?:to sql|queries|querying)|conversational analytics"),
("Business tools","requirements gathering",r"requirements? gathering|gather(?:ing)?(?: and document(?:ing)?)? (?:the )?(?:business |data |reporting |user |stakeholder )?requirements|(?:business|data|reporting|analytical|analytics|user|functional) requirements|business analysis|acceptance criteria|user stories"),
# Business Process Outsourcing is an industry (call centres), not process work.
("Business tools","process improvement",r"process improvements?|business process(?:es)?(?! outsourcing)|process mapping|improv(?:e|ing) (?:business |existing |internal )?processes|process (?:optimi[sz]ation|re-?engineering)"),
("Business tools","Lean / Six Sigma",r"six sigma|lean six|(?-i:\bLEAN\b)|\blean\b(?= (?:methodolog|principles|management|practices|certification|thinking))|\bkaizen\b"),
# Domain knowledge.
("Domain knowledge","healthcare knowledge",r"health ?care (?:data|systems?|terminology|environment|sector|settings?|experience|industry|operations)|clinical (?:data|terminology|systems?|workflows?)|health (?:information|records|data)|electronic (?:health|medical) records?|(?-i:\b(?:HL7|EHR|CIHI)\b)|\bcerner\b|medical terminology|healthcare analytics"),
("Domain knowledge","financial analysis / FP&A",r"financial (?:analysis|modell?ing|planning|statements)|fp&a|variance analysis|unit economics|budget(?:ing)? and forecast"),
("Domain knowledge","investment performance / attribution",r"performance attribution|return attribution|attribution, risk|risk (?:and|&) exposure|investment (?:performance|analytics)|portfolio management theory"),
("Domain knowledge","accounting (GAAP / IFRS)",r"\bgaap\b|\bifrs\b|revenue recognition|accounting (?:knowledge|principles|standards|concepts|working knowledge)|knowledge of (?:[a-z]+(?:,\s*(?:and\s+)?|\s+and\s+))*accounting|(?:basic|sound) accounting"),
("Domain knowledge","risk management / regulatory compliance",r"risk management|regulatory (?:compliance|requirements|reporting|frameworks)"),
# B2B marketing's lead funnel. Uppercase MQL only; "SQLs" is left out, it reads as the language.
("Domain knowledge","demand generation / lead funnel (MQLs)",r"demand gen(?:eration)?\b|(?-i:\bMQLs?\b)|marketing.qualified leads?"
 r"|(?:marketing|sales|lead) funnels?"),
("Domain knowledge","epidemiology / biostatistics",r"epidemiolog|biostatistic"),
# Uppercase IoT: "NYSE: IOT" is a ticker.
("Domain knowledge","IoT / sensor data",r"(?-i:\bIoT\b)|internet of things|sensor data"),
# A software supply chain (dependencies) is security, not logistics.
("Domain knowledge","supply chain / inventory",r"(?<!software )(?<!data )supply.chain(?! (?:security|attacks?))|inventory (?:control|management|planning|optimi[sz]ation)|procurement (?:data|analytics|processes|systems)|demand planning"),
("Domain knowledge","fraud / risk analytics",r"fraud (?:detection|prevention|analytics|risk|models?|rules)|anti.?fraud|risk analytics|fraud and (?:risk|abuse)"),
# Bare "retail" is often the employer ("retail partners"), so only next to e-commerce or consumer goods.
# Lowercase only: "Contoso Retail analytics" is a company name.
("Domain knowledge","e-commerce / retail",r"e-?commerce|online marketplaces?|(?-i:\bretail) (?:analytics|data|industry|environment|sector|operations)|(?-i:\bretail)(?=,? (?:or |and )?(?:e-?commerce|consumer))"),
("Domain knowledge","trust & safety / content moderation",r"content moderation|trust (?:and|&) safety|harmful content|(?:effective|user|content) moderation|moderation (?:workflows|decisions|systems|tools)"),
("Domain knowledge","ad tech / programmatic advertising",r"\bad ?tech\b|programmatic (?:advertising|ads?)|\bads? (?:auctions?|bidding|pacing|marketplace|systems|platforms?|targeting)\b|auction theory|real.time bidding|(?-i:\bRTB\b)"),
("Domain knowledge","cryptography",r"cryptograph"),
# soft skills
("Soft skills","communication",r"communicat"),
("Soft skills","collaboration/teamwork",r"collaborat|team ?work|cross.functional|team player|(?:works?|interact) well with others"),
("Soft skills","problem solving",r"problem.solv|problem decomposition|break(?:ing)? down (?:complex |ambiguous |large )?problems"),
("Soft skills","stakeholder management",r"stakeholder|relationships with (?:key |our )?(?:internal|external|partners|clients|customers)|partner relationships"),
("Soft skills","attention to detail",r"attention to detail|detail.oriented|meticulous"),
("Soft skills","analytical thinking",r"analytical"),
("Soft skills","critical thinking",r"critical thinking"),
("Soft skills","presentation / storytelling",r"present(?:ation|ing|ed) (?:skills|findings|results|insights|to)|storytelling|\bpresentations?\b(?! layer)"),
("Soft skills","time management / prioritization",r"time management|prioriti[sz]|multi.?task|deadlines|multiple (?:tasks|projects|priorities)|competing priorities|several (?:projects|tasks|things) at once"),
("Soft skills","independent / self-starter",r"independently|self.starter|self.motivated|self.directed|self.driven|autonomous|initiative|(?:minimal|limited|little) supervision|on (?:your|my|their) own"),
("Soft skills","leadership / mentoring",r"leadership|mentor"),
("Soft skills","curiosity / learning",r"curious|curiosity|eager(?:ness)? to learn|continuous learning|growth mindset|(?:motivated|willing(?:ness)?|desire|keen) to learn|quick learner|learns? quickly"),
("Soft skills","business acumen",r"business acumen|business needs|business problems"),
("Soft skills","documentation",r"document(?:ation|ing)"),
("Soft skills","adaptability",r"adaptab|fast.paced|ambiguity"),
("Soft skills","ownership / accountability",r"(?<!home )(?<!employee )(?<!share)\bownership\b|accountab|own (?:the|your) (?:work|outcomes?|projects?|results|deliverables)"),
("Soft skills","customer / client focus",r"(?:customer|client|user|patient).(?:first|centric|centred|centered|focused|facing|obsessed)|customer (?:service|satisfaction)|client service|service (?:mentality|orientation)"),
("Soft skills","teaching / knowledge sharing",r"knowledge (?:sharing|transfer)|shar(?:e|es|ing) (?:your |their |our )?knowledge|(?:provide|deliver|conduct)\w* training|train(?:ing)? (?:users|staff|colleagues|others|team members|end users)|training (?:materials|sessions)|educat(?:e|ing) (?:users|stakeholders|teams|others)|\bteach|\bcoach"),
("Soft skills","judgment",r"\bjudge?ments?\b|critically (?:evaluate|assess|review)|challenge assumptions|discernment"),
("Soft skills","integrity / trustworthiness",r"(?<!data )\bintegrity\b(?! of)|trustworth|\bhonest|ethical (?:conduct|standards|behaviou?r)"),
("Soft skills","discretion / confidentiality",r"\bdiscretion\b|confidentiality|(?:handl|maintain)\w* (?:sensitive|confidential)"),
("Soft skills","influence / negotiation",r"influenc(?:e|ing) (?:stakeholders|decisions|others|leaders|without)|persua|negotiat"),
("Soft skills","proactive",r"proactiv"),
("Soft skills","entrepreneurial / bias to action",r"entrepreneur|bias (?:to|toward|towards|for) action|builder mindset|scrappy|startup (?:mindset|environment|experience)"),
("Soft skills","relationship building",r"(?:build|develop|maintain|cultivat|foster|nurtur|strengthen)\w* (?:\w+ ){0,3}relationships|relationship.building|trusted (?:partner|advisor)"),
("Soft skills","rigour / thoroughness",r"rigou?r|methodical|\bthorough"),
("Soft skills","resilience / working under pressure",r"under pressure|resilien|persever|tenaci"),
("Soft skills","continuous improvement",r"continuous(?:ly)? improv|improvement mindset"),
("Soft skills","creativity / innovation",r"creativ|innovative (?:solutions|ideas|thinking|approaches)|out.of.the.box|think outside"),
("Soft skills","strategic thinking",r"strategic (?:thinking|thinker|mindset)|think strategically"),
("Soft skills","systems thinking",r"systems thinking|systems thinker"),
("Soft skills","product mindset",r"product.minded|product (?:mindset|sense|thinking|intuition)"),
("Soft skills","organization",r"organi[sz]ational skills|(?:well|highly|very|extremely|stay) organi[sz]ed|strong organi[sz]ation"),
("Soft skills","empathy / compassion",r"empath|compassion"),
("Soft skills","interpersonal skills",r"interpersonal"),
# Credentials
# \b before "b.sc": "subscriptions" contains "bsc".
("Credentials","Bachelor's degree",r"bachelor|undergraduate degree|\bb\.?sc|\bbs\b|\bba\b"),
("Credentials","CFA / FRM / CIPM",r"(?-i)\bCFA\b|\bFRM\b|\bCIPM\b"),
("Credentials","CBAP / IIBA",r"\bcbap\b|\bccba\b|\biiba\b|\bbabok\b"),
("Credentials","cloud certification",r"(?:aws|azure|google cloud|gcp|snowflake|databricks)[^.\n]{0,40}certifi|certifi\w* in google|snowpro|professional data engineer"
 r"|aws certified|azure [\w ]{0,30}associate\b"),
# "MS" before a Microsoft product ("MS SQL", "MS Office") is Microsoft, not a Master of Science.
("Credentials","Master's degree",r"master'?s|\bm\.?sc\b|\bms\b(?![ -]?(?:sql|office|excel|word|access|teams|project|dynamics|azure|365|outlook|powerpoint|visio|sharepoint|fabric|power))|graduate degree"),
("Credentials","PhD",r"\bph\.?d"),
("Credentials","degree in CS",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)(?:(?!experience)[^.;]){0,80}computer science|computer science[^.;]{0,30}degree"),
("Credentials","degree in statistics/math",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)(?:(?!experience)[^.;]){0,80}(?:statistics|mathematics|math)\b"),
("Credentials","degree in engineering",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)(?:(?!experience)[^.;]){0,80}engineering"),
("Credentials","degree in economics/business",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)(?:(?!experience)[^.;]){0,40}\b(?:in|of)\b(?:(?!experience)[^.;]){0,40}\b(?:economics|business|commerce|finance)"),
]

# Products and the platform, family or close cousin they belong with: related, but not the
# same skill (Looker Studio experience doesn't show Looker).
RELATED = {"AWS S3": "AWS", "AWS Lambda": "AWS", "Amazon SageMaker": "AWS", "Amazon Bedrock": "AWS",
           "Amazon Kinesis": "AWS", "AWS Glue": "AWS", "Amazon Athena": "AWS",
           "Amazon EMR": "AWS", "Amazon EC2": "AWS", "AWS CloudFormation": "AWS", "AWS API Gateway": "AWS",
           "Amazon CloudWatch": "AWS", "Amazon RDS": "AWS", "Azure OpenAI": "Azure", "Node.js": "JavaScript", "Google Cloud Composer": "GCP", "MongoDB": "NoSQL", "DynamoDB": "NoSQL",
           "Cassandra": "NoSQL", "Cosmos DB": "NoSQL", "Redis": "NoSQL", "Confluent": "Kafka",
           "Claude / Claude Code": "LLMs / generative AI", "RAG (retrieval-augmented generation)": "LLMs / generative AI", "OpenAI API": "LLMs / generative AI", "Azure Machine Learning": "Azure", "Vertex AI": "GCP", "MLflow": "MLOps",
           "Power Query": "Microsoft Power Platform", "Power Automate": "Microsoft Power Platform",
           "Power Apps": "Microsoft Power Platform", "Dataverse": "Microsoft Power Platform",
           "Looker Studio": "Looker", "Google Cloud Storage": "GCP",
           "Google Cloud Dataflow / Apache Beam": "GCP", "Google Cloud Pub/Sub": "GCP",
           "prompt engineering": "LLMs / generative AI", "SQL window functions / CTEs": "SQL",
           "SQL stored procedures": "SQL", "Amazon SQS / SNS": "AWS", "Amazon ECS": "AWS",
           "Delta Lake": "Databricks", "Unity Catalog": "Databricks", "Snowflake Cortex": "Snowflake",
           "Dataform": "GCP", "Agentforce": "Salesforce/CRM", "ELK Stack": "Elasticsearch",
           "SOQL": "Salesforce/CRM", "Acumatica": "ERP (SAP/Oracle/Workday)",
           "Snowpark": "Snowflake", "Ruby on Rails": "Ruby", "Three.js / WebGL": "JavaScript",
           "Azure integration services (Logic Apps / Service Bus / Event Grid)": "Azure"}

# The kind of tool each one is. An open list ("e.g. Tableau, QuickSight", "or similar tools")
# takes its type from the tools it names, so any tool of that type can stand in. Excel isn't a
# BI / visualization tool here (Jake's call, Oct 18 2026): it's a stretch for "dashboards (e.g. ...)".
_TYPES = {
    "programming language": ["SQL", "Python", "R", "Java", "JavaScript", "TypeScript", "C#/.NET", "C/C++", "Go",
                             "Scala", "Julia", "Perl", "Ruby", "PowerShell", "VBA", "Bash/Shell", "Kotlin/Swift",
                             "Rust", "MATLAB", "SAS", "PHP", "kdb+/q", "SOQL"],
    "statistical software": ["SAS", "SPSS", "Stata", "MATLAB", "R", "Python", "Julia"],
    "ML framework": ["PyTorch", "TensorFlow/Keras", "JAX", "scikit-learn", "XGBoost/LightGBM", "Hugging Face",
                     "LangChain/LlamaIndex", "spaCy / NLTK", "vLLM"],
    "data library": ["pandas", "NumPy", "scikit-learn", "matplotlib/seaborn/plotly", "Jupyter"],
    "web framework": ["React", "FastAPI/Flask/Django", "Angular", "Vue", "Spring", "Node.js", "Ruby on Rails"],
    "ORM": ["ORM (Hibernate / SQLAlchemy)"],
    "3D / graphics": ["Three.js / WebGL", "Unity / Unreal Engine"],
    "AI assistant": ["Claude / Claude Code", "ChatGPT", "GitHub Copilot", "Microsoft Copilot", "Cursor", "Codex",
                     "Gemini"],
    "BI / visualization tool": ["Power BI", "Tableau", "Looker", "Looker Studio", "Qlik", "Superset", "Metabase",
                                "Sigma", "MicroStrategy", "Cognos", "Amazon QuickSight", "SSIS/SSRS", "Hex"],
    "product analytics": ["Google Analytics", "Amplitude / Mixpanel", "Statsig"],
    "data warehouse": ["Snowflake", "Databricks", "BigQuery", "Redshift", "Microsoft Fabric / Azure Synapse / ADF"],
    "table format": ["Delta Lake", "Apache Iceberg"],
    "data catalog": ["Unity Catalog"],
    "database": ["SQL", "NoSQL", "MongoDB", "DynamoDB", "Cassandra", "Cosmos DB", "Redis", "Elasticsearch",
                 "vector databases", "Supabase"],
    "big data / streaming": ["Spark/PySpark", "Kafka", "Flink", "Hadoop/Hive", "Amazon Kinesis", "Databricks",
                             "Amazon EMR", "Confluent", "Snowpark"],
    "data warehouse / query engine": ["Amazon Athena", "Presto/Trino"],
    "orchestration / ETL tool": ["Airflow", "Prefect", "Dagster", "dbt", "Fivetran", "SSIS/SSRS", "Alteryx", "AWS Glue",
                                 "Google Cloud Composer",
                                 "Microsoft Fabric / Azure Synapse / ADF", "Dataform", "SQLMesh", "VisualCron"],
    "cloud platform": ["AWS", "Azure", "GCP", "AWS S3", "AWS Lambda", "Amazon SageMaker", "Amazon Bedrock",
                       "Amazon Kinesis", "Azure Machine Learning", "Vertex AI", "AWS Glue", "Amazon Athena",
                       "Amazon EMR", "Amazon EC2", "AWS CloudFormation", "Google Cloud Composer", "Google Cloud Storage",
                       "Google Cloud Dataflow / Apache Beam", "Google Cloud Pub/Sub", "Amazon SQS / SNS", "Amazon ECS",
                       "AWS API Gateway", "Amazon CloudWatch", "Amazon RDS", "Azure OpenAI",
                       "Azure integration services (Logic Apps / Service Bus / Event Grid)"],
    "test tool": ["Playwright", "Selenium", "Cypress", "Postman", "JMeter / k6", "Jest / Vitest"],
    "ML / AI platform": ["Amazon SageMaker", "Azure Machine Learning", "Vertex AI", "MLflow", "Databricks",
                         "Amazon Bedrock", "Snowflake Cortex", "Dataiku", "Azure OpenAI"],
    "DevOps tool": ["Docker", "Kubernetes", "CI/CD", "Git", "Terraform/IaC", "Linux/Unix", "Datadog", "Ansible / Puppet",
                    "AWS CloudFormation", "Grafana", "Prometheus", "ELK Stack"],
    "business software": ["Salesforce/CRM", "ERP (SAP/Oracle/Workday)", "Jira/Confluence", "Visio / diagramming",
                          "Microsoft Access", "Microsoft Word", "Microsoft Office", "SharePoint", "Excel",
                          "Microsoft Outlook", "Microsoft PowerPoint", "Microsoft Teams", "Google Sheets / Workspace",
                          "ServiceNow", "Stripe", "test management (TestRail, qTest, Xray)",
                          "project controls (Primavera P6, EcoSys)",
                          "Microsoft Power Platform", "Power Apps", "Power Automate", "Power Query", "Dataverse",
                          "Anaplan", "Marketo", "Agentforce", "Bloomberg", "Acumatica"],
}
TOOL_TYPES: dict[str, set[str]] = {}
for _type, _names in _TYPES.items():
    for _n in _names:
        TOOL_TYPES.setdefault(_n, set()).add(_type)


HARD_CATEGORIES = {c for c, _, _ in T} - {"Soft skills", "Credentials"}


def _compile(p: str) -> re.Pattern[str]:
    if p.startswith("(?-i)"):
        return re.compile(p[5:].replace("(?-i)", ""))
    return re.compile(p, re.I)


@lru_cache(maxsize=1)
def compiled() -> list[tuple[str, str, re.Pattern[str]]]:
    return [(cat, name, _compile(p)) for cat, name, p in T]


@lru_cache(maxsize=1)
def _categories() -> dict[str, str]:
    out: dict[str, str] = {}
    for cat, n, _ in T:
        out.setdefault(n, cat)
    return out


def category(name: str) -> str | None:
    return _categories().get(name)


def is_hard(name: str) -> bool:
    return category(name) in HARD_CATEGORIES


def find(text: str) -> set[str]:
    """Display names of every taxonomy skill mentioned in `text`."""
    return {name for _, name, rx in compiled() if rx.search(text)}


def find_wordings(text: str) -> dict[str, set[str]]:
    """Each taxonomy skill mentioned in `text`, with the exact words that matched it.

    A pattern may stop inside a word ("data warehous", "visualiz"), so the match is
    extended to the end of that word: callers look the wording up as a whole phrase.
    """
    out: dict[str, set[str]] = {}
    for _, name, rx in compiled():
        for m in rx.finditer(text):
            end = m.end()
            while end < len(text) and text[end].isalnum():
                end += 1
            out.setdefault(name, set()).add(text[m.start():end])
    return out


def canonical(term: str) -> str | None:
    """The taxonomy skill a posting term refers to ("Postgres" -> "SQL"), or None."""
    t = term.strip()
    for _, name, rx in compiled():
        if name.lower() == t.lower():
            return name
    hits = [name for _, name, rx in compiled() if rx.search(t)]
    return hits[0] if hits else None


# Words that don't narrow a skill: "key performance indicators" is still KPIs.
_FILLER = {"indicator", "indicators", "skill", "skills", "experience", "tool", "tools", "knowledge",
           "proficiency", "concept", "concepts", "technique", "techniques", "method", "methods",
           "database", "databases", "platform", "platforms", "language", "languages", "programming",
           "the", "of", "and", "in", "with", "a", "an"}


def is_synonym(term: str) -> bool:
    """True when `term` as a whole is a name for its skill ("key performance indicators" for KPIs),
    not a narrower phrase that only contains one ("reporting pipelines" contains "reporting")."""
    t = term.strip()
    canon = canonical(t)
    if not canon:
        return False
    if canon.lower() == t.lower():
        return True
    for _, n, rx in compiled():
        m = rx.search(t) if n == canon else None
        if m:
            rest = re.findall(r"[a-z0-9+#]+", (t[:m.start()] + " " + t[m.end():]).lower())
            if all(w in _FILLER for w in rest):
                return True
    return False


def mentions(name: str, text: str) -> bool:
    """True when `text` mentions skill `name` by any of its synonyms."""
    for _, n, rx in compiled():
        if n == name:
            return bool(rx.search(text))
    return False


def us_spelling(text: str) -> str:
    """`text` with British/Canadian spellings turned into US ones (see src/tailor/wording.py)."""
    return wording.us_spelling(text)


def exact(term: str, text: str) -> bool:
    """True when `text` contains `term` itself as a whole phrase, the way an ATS keyword
    search finds it (plural and hyphen/space ignored, spelling exact; src/tailor/wording.py).

    ATSs like Taleo and Lever search exact wording, so exact matches get full
    credit and taxonomy synonyms only partial credit.
    """
    return wording.ats(term, text)
