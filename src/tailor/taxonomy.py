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
("Languages","JavaScript",r"javascript|\bnode\.?js\b"),
("Languages","TypeScript",r"typescript"),
("Languages","C#/.NET",r"c#|\.net\b"),
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
# BI / analytics
# Capitalised "Excel" is the tool; lowercase "excel" is usually the verb ("our people can excel").
("BI & analytics","Excel",r"(?-i)\bExcel\b|\bEXCEL\b|(?i:\b(?:ms|microsoft|advanced|intermediate) excel\b|\bexcel (?:skills|spreadsheets?|formulas?|macros|vba|models?)\b"
 r"|spreadsheets?|pivot tables?|vlookup|xlookup)"),
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
("BI & analytics","KPIs/metrics",r"\bkpis?\b|key performance|metrics"),
("BI & analytics","A/B testing / experimentation",r"a/b test|experiment(?:ation|al design| design)|\bab test"),
("BI & analytics","Power Query",r"power query"),
("BI & analytics","Power Automate",r"power automate"),
("BI & analytics","Power Apps",r"power apps"),
("BI & analytics","Microsoft Power Platform",r"power platform"),
("BI & analytics","Dataverse",r"dataverse"),
("BI & analytics","Superset",r"\bsuperset\b"),
("BI & analytics","Metabase",r"metabase"),
("BI & analytics","Sigma",r"(?-i)\bSigma\b(?! ?(?:Xi|Chi))|sigma computing"),
("BI & analytics","MicroStrategy",r"microstrategy"),
("BI & analytics","Cognos",r"cognos"),
("BI & analytics","Amplitude / Mixpanel",r"(?-i)\bAmplitude\b|\b[Mm]ixpanel\b"),
# Data engineering / warehouse
("Data platforms","Snowflake",r"snowflake"),
("Data platforms","Databricks",r"databricks"),
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
("Data platforms","Hadoop/Hive",r"hadoop|\bhive\b|\bhbase\b"),
("Data platforms","ETL/ELT",r"\betl\b|\belt\b|extract, transform"),
("Data platforms","data pipelines",r"data pipelines?|etl pipelines?|ml pipelines?|pipelines? (?:for|that) data"),
("Data platforms","data warehouse",r"data warehous|warehouse|data lake|lakehouse"),
("Data platforms","data modeling",r"data model|dimensional model|star schema"),
("Data platforms","data quality / validation",r"data quality|data integrity|data validation|data cleans|data cleaning"
 r"|\bdata qa\b|\bvalidated\b[^.;]{0,100}\bdata\b"),
("Data platforms","data governance",r"data governance|data stewardship|metadata"),
# Relational databases (PostgreSQL, MySQL, SQL Server, SQLite) stay under SQL: SQL skill carries
# over between them. NoSQL databases each work differently, so each is its own skill (Jake, Oct 18 2026).
("Data platforms","NoSQL",r"\bnosql\b"),
("Data platforms","MongoDB",r"mongodb|\bmongo\b"),
("Data platforms","DynamoDB",r"dynamodb"),
("Data platforms","Cassandra",r"cassandra"),
("Data platforms","Cosmos DB",r"cosmos ?db"),
("Data platforms","Redis",r"\bredis\b"),
("Data platforms","APIs / REST",r"\bapis?\b|\brest(ful)?\b"),
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
("Cloud & DevOps","Amazon Kinesis",r"kinesis"),
("Cloud & DevOps","AWS Glue",r"(?-i)\b(?:AWS )?Glue\b"),
("Cloud & DevOps","Amazon Athena",r"(?-i)\bAthena\b"),
("Cloud & DevOps","Amazon EMR",r"(?-i)\bEMR\b(?! (?:system|record|data))"),
("Cloud & DevOps","Amazon EC2",r"\bec2\b"),
("Cloud & DevOps","AWS CloudFormation",r"cloudformation"),
("Cloud & DevOps","Google Cloud Composer",r"cloud composer"),
("Cloud & DevOps","Datadog",r"datadog"),
("Cloud & DevOps","Ansible / Puppet",r"\bansible\b|(?-i:\bPuppet\b)"),
("Cloud & DevOps","Azure",r"\bazure\b"),
("Cloud & DevOps","Azure Machine Learning",r"azure machine learning|azure ml\b"),
("Cloud & DevOps","GCP",r"\bgcp\b|google cloud(?! oauth)"),
("Cloud & DevOps","Vertex AI",r"vertex ai"),
("Cloud & DevOps","Docker",r"docker|containeri[sz]"),
("Cloud & DevOps","Kubernetes",r"kubernetes|\bk8s\b"),
("Cloud & DevOps","CI/CD",r"ci/cd|continuous integration|continuous deliver|github actions|jenkins"),
("Cloud & DevOps","Git",r"\bgit\b|github(?! copilot)|gitlab|bitbucket|version control"),
("Cloud & DevOps","Terraform/IaC",r"terraform|infrastructure as code"),
("Cloud & DevOps","MLOps",r"mlops|model deployment|deploy(?:ing)? models|model monitoring"),
("Cloud & DevOps","MLflow",r"mlflow"),
("Cloud & DevOps","testing (unit/automated)",r"unit test|automated test|test automation|pytest|\btdd\b"),
("Cloud & DevOps","microservices",r"microservice"),
("Cloud & DevOps","distributed systems",r"distributed system"),
# ML / stats methods
("ML & statistics","machine learning",r"machine learning|\bml\b"),
("ML & statistics","AI (any mention)",r"\bai\b|artificial intelligence"),
("ML & statistics","statistics",r"statistic"),
("ML & statistics","predictive modeling",r"predictive|forecast"),
("ML & statistics","regression",r"regression"),
("ML & statistics","classification",r"classification|classifier"),
("ML & statistics","clustering/segmentation",r"cluster|segmentation"),
("ML & statistics","deep learning / neural nets",r"deep learning|neural net"),
("ML & statistics","NLP",r"\bnlp\b|natural language"),
("ML & statistics","embeddings",r"\bembeddings?\b"),
("ML & statistics","LLMs / generative AI",r"\bllms?\b|large language|generative ai|\bgenai\b|\bgpt\b|prompt engineering|\brag\b|retrieval.augmented"),
("ML & statistics","computer vision",r"computer vision|image processing"),
("ML & statistics","time series",r"time.series"),
("ML & statistics","hypothesis testing / inference",r"hypothesis|statistical inference|significance test|causal"),
("ML & statistics","feature engineering",r"feature engineering"),
("ML & statistics","model evaluation/validation",r"model (?:evaluation|validation|performance)|cross.validation"),
("ML & statistics","optimization / OR",r"optimi[sz]ation|operations research|linear programming"),
("ML & statistics","recommendation systems",r"recommend(?:er|ation) (?:system|engine)"),
("ML & statistics","survival analysis",r"survival analysis|churn"),
("ML & statistics","Bayesian methods",r"bayesian"),
("ML & statistics","mathematics (linear algebra, calculus)",r"linear algebra|calculus|mathematic"),
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
("Business tools","Microsoft Office",r"microsoft office|ms office|office 365|microsoft 365|word, excel|powerpoint"),
("Business tools","Agile/Scrum",r"\bagile\b|scrum|kanban|sprint"),
("Business tools","project management",r"project management|project manager|pmp"),
("Business tools","GIS",r"\bgis\b|arcgis|geospatial"),
("BI & analytics","Amazon QuickSight",r"quicksight"),
("Business tools","SharePoint",r"sharepoint"),
("Data platforms","GraphQL",r"graphql"),
("Data platforms","JSON",r"\bjson\b"),
("ML & statistics","AI agents / agentic AI / MCP",r"agentic|ai agents?|\bmcp\b|model context protocol|langgraph"),
("Cloud & DevOps","SDLC",r"\bsdlc\b|software development life ?cycle"),
("Cloud & DevOps","networking (TCP/IP)",r"tcp/ip|\btcp\b|\budp\b|networking protocols"),
("Cloud & DevOps","QA / UAT",r"\buat\b|user acceptance|quality assurance"),
# soft skills
("Soft skills","communication",r"communicat"),
("Soft skills","collaboration/teamwork",r"collaborat|team ?work|cross.functional"),
("Soft skills","problem solving",r"problem.solv"),
("Soft skills","stakeholder management",r"stakeholder"),
("Soft skills","attention to detail",r"attention to detail|detail.oriented|meticulous"),
("Soft skills","analytical thinking",r"analytical"),
("Soft skills","critical thinking",r"critical thinking"),
("Soft skills","presentation / storytelling",r"present(?:ation|ing) (?:skills|findings|results|insights|to)|storytelling|presentations"),
("Soft skills","time management / prioritization",r"time management|prioriti[sz]|multi.?task|deadlines"),
("Soft skills","independent / self-starter",r"independently|self.starter|self.motivated|autonomous|initiative"),
("Soft skills","leadership / mentoring",r"leadership|mentor"),
("Soft skills","curiosity / learning",r"curious|curiosity|eager to learn|continuous learning|growth mindset"),
("Soft skills","business acumen",r"business acumen|business needs|business problems|business requirements"),
("Soft skills","documentation",r"document(?:ation|ing)"),
("Soft skills","adaptability",r"adaptab|fast.paced|ambiguity"),
# Credentials
("Credentials","Bachelor's degree",r"bachelor|undergraduate degree|b\.?sc|\bbs\b|\bba\b"),
("Credentials","Master's degree",r"master'?s|\bm\.?sc\b|\bms\b|graduate degree"),
("Credentials","PhD",r"\bph\.?d"),
("Credentials","degree in CS",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)[^.;]{0,80}computer science|computer science[^.;]{0,30}degree"),
("Credentials","degree in statistics/math",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)[^.;]{0,80}(?:statistics|mathematics|math)\b"),
("Credentials","degree in engineering",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)[^.;]{0,80}engineering"),
("Credentials","degree in economics/business",r"(?:degree|bachelor|master|diploma|b\.?sc|ph\.?d|post-secondary|education)[^.;]{0,80}(?:economics|business|commerce|finance)"),
]

# Products and the platform, family or close cousin they belong with: related, but not the
# same skill (Looker Studio experience doesn't show Looker).
RELATED = {"AWS S3": "AWS", "AWS Lambda": "AWS", "Amazon SageMaker": "AWS", "Amazon Bedrock": "AWS",
           "Amazon Kinesis": "AWS", "AWS Glue": "AWS", "Amazon Athena": "AWS",
           "Amazon EMR": "AWS", "Amazon EC2": "AWS", "AWS CloudFormation": "AWS", "Google Cloud Composer": "GCP", "MongoDB": "NoSQL", "DynamoDB": "NoSQL",
           "Cassandra": "NoSQL", "Cosmos DB": "NoSQL", "Redis": "NoSQL", "Confluent": "Kafka",
           "Claude / Claude Code": "LLMs / generative AI", "OpenAI API": "LLMs / generative AI", "Azure Machine Learning": "Azure", "Vertex AI": "GCP", "MLflow": "MLOps",
           "Power Query": "Microsoft Power Platform", "Power Automate": "Microsoft Power Platform",
           "Power Apps": "Microsoft Power Platform", "Dataverse": "Microsoft Power Platform",
           "Looker Studio": "Looker"}

# The kind of tool each one is. An open list ("e.g. Tableau, QuickSight", "or similar tools")
# takes its type from the tools it names, so any tool of that type can stand in. Excel isn't a
# BI / visualization tool here (Jake's call, Oct 18 2026): it's a stretch for "dashboards (e.g. ...)".
_TYPES = {
    "programming language": ["SQL", "Python", "R", "Java", "JavaScript", "TypeScript", "C#/.NET", "C/C++", "Go",
                             "Scala", "Julia", "Perl", "Ruby", "PowerShell", "VBA", "Bash/Shell", "Kotlin/Swift",
                             "Rust", "MATLAB", "SAS"],
    "statistical software": ["SAS", "SPSS", "Stata", "MATLAB", "R", "Python", "Julia"],
    "ML framework": ["PyTorch", "TensorFlow/Keras", "JAX", "scikit-learn", "XGBoost/LightGBM", "Hugging Face",
                     "LangChain/LlamaIndex", "spaCy / NLTK", "vLLM"],
    "data library": ["pandas", "NumPy", "scikit-learn", "matplotlib/seaborn/plotly", "Jupyter"],
    "web framework": ["React", "FastAPI/Flask/Django", "Angular", "Vue", "Spring"],
    "AI assistant": ["Claude / Claude Code", "ChatGPT", "GitHub Copilot", "Microsoft Copilot", "Cursor", "Codex",
                     "Gemini"],
    "BI / visualization tool": ["Power BI", "Tableau", "Looker", "Looker Studio", "Qlik", "Superset", "Metabase",
                                "Sigma", "MicroStrategy", "Cognos", "Amazon QuickSight", "SSIS/SSRS"],
    "product analytics": ["Google Analytics", "Amplitude / Mixpanel"],
    "data warehouse": ["Snowflake", "Databricks", "BigQuery", "Redshift", "Microsoft Fabric / Azure Synapse / ADF"],
    "database": ["SQL", "NoSQL", "MongoDB", "DynamoDB", "Cassandra", "Cosmos DB", "Redis", "Elasticsearch",
                 "vector databases"],
    "big data / streaming": ["Spark/PySpark", "Kafka", "Flink", "Hadoop/Hive", "Amazon Kinesis", "Databricks",
                             "Amazon EMR", "Confluent"],
    "data warehouse / query engine": ["Amazon Athena"],
    "orchestration / ETL tool": ["Airflow", "Prefect", "Dagster", "dbt", "Fivetran", "SSIS/SSRS", "Alteryx", "AWS Glue",
                                 "Google Cloud Composer",
                                 "Microsoft Fabric / Azure Synapse / ADF"],
    "cloud platform": ["AWS", "Azure", "GCP", "AWS S3", "AWS Lambda", "Amazon SageMaker", "Amazon Bedrock",
                       "Amazon Kinesis", "Azure Machine Learning", "Vertex AI", "AWS Glue", "Amazon Athena",
                       "Amazon EMR", "Amazon EC2", "AWS CloudFormation", "Google Cloud Composer"],
    "ML / AI platform": ["Amazon SageMaker", "Azure Machine Learning", "Vertex AI", "MLflow", "Databricks",
                         "Amazon Bedrock"],
    "DevOps tool": ["Docker", "Kubernetes", "CI/CD", "Git", "Terraform/IaC", "Linux/Unix", "Datadog", "Ansible / Puppet",
                    "AWS CloudFormation"],
    "business software": ["Salesforce/CRM", "ERP (SAP/Oracle/Workday)", "Jira/Confluence", "Visio / diagramming",
                          "Microsoft Access", "Microsoft Word", "Microsoft Office", "SharePoint", "Excel",
                          "Microsoft Outlook", "Microsoft PowerPoint", "Microsoft Teams", "Google Sheets / Workspace",
                          "ServiceNow", "Stripe", "test management (TestRail, qTest, Xray)",
                          "project controls (Primavera P6, EcoSys)",
                          "Microsoft Power Platform", "Power Apps", "Power Automate", "Power Query", "Dataverse"],
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


def category(name: str) -> str | None:
    for cat, n, _ in T:
        if n == name:
            return cat
    return None


def is_hard(name: str) -> bool:
    return category(name) in HARD_CATEGORIES


def find(text: str) -> set[str]:
    """Display names of every taxonomy skill mentioned in `text`."""
    return {name for _, name, rx in compiled() if rx.search(text)}


def find_wordings(text: str) -> dict[str, set[str]]:
    """Each taxonomy skill mentioned in `text`, with the exact words that matched it."""
    out: dict[str, set[str]] = {}
    for _, name, rx in compiled():
        for m in rx.finditer(text):
            out.setdefault(name, set()).add(m.group(0))
    return out


def canonical(term: str) -> str | None:
    """The taxonomy skill a posting term refers to ("Postgres" -> "SQL"), or None."""
    t = term.strip()
    for _, name, rx in compiled():
        if name.lower() == t.lower():
            return name
    hits = [name for _, name, rx in compiled() if rx.search(t)]
    return hits[0] if hits else None


def mentions(name: str, text: str) -> bool:
    """True when `text` mentions skill `name` by any of its synonyms."""
    for _, n, rx in compiled():
        if n == name:
            return bool(rx.search(text))
    return False


def exact(term: str, text: str) -> bool:
    """True when `text` contains `term` itself as a whole phrase (case-insensitive).

    ATSs like Taleo and Lever search exact wording, so exact matches get full
    credit and taxonomy synonyms only partial credit.
    """
    t = re.escape(term.strip())
    return bool(re.search(rf"(?<![\w+#]){t}(?![\w+#])", text, re.I))
