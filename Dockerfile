# The job scrape (scripts/aggregate.py) as the Azure Container Apps job (Azure plan, phase 5;
# docs/azure-scrape-job.md). Built by .github/workflows/scrape-image.yml from the repo alone:
# nothing git-ignored (materials/, .env, token.json, jobs.db) is ever in the image. Settings
# and secrets come from the job's environment; the vault files scoring needs come from Postgres.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY scripts ./scripts
COPY config ./config

ARG IMAGE_SHA=dev
# PYTHONPATH: the scripts import src.* (on the desktop the project is installed into .venv).
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app IMAGE_SHA=$IMAGE_SHA \
    JOBSEARCH_DB=postgres SCRAPE_HOST=azure

RUN useradd --create-home scraper && chown -R scraper /app
USER scraper
CMD ["python", "scripts/aggregate.py"]
