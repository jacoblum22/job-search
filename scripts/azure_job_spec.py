"""Write the Azure Container Apps job definition for the daily scrape (docs/azure-scrape-job.md).

    uv run python scripts/azure_job_spec.py --environment-id <id> --out <file>

The result is the ARM body `az rest --method put` sends: schedule, size, image, and the
secrets read from .env (JOBSEARCH_PG_URL, Adzuna, CareerJet, Himalayas) and token.json
(Gmail). It holds those secrets, so scripts/azure_scrape_job.ps1 writes it to a temp file
and deletes it straight after; never save it in the repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent

IMAGE = "ghcr.io/jacoblum22/job-search-scrape:jake"
# 14:00 UTC: 7:00 in Vancouver in summer time, 6:00 in winter; before the 7:30 skills review
# and the 9:00 tailoring run, which skips its own scrape when this one finished.
CRON = "0 14 * * *"
# .env name -> secret name. Only JOBSEARCH_PG_URL is required.
SECRETS = {
    "JOBSEARCH_PG_URL": "pg-url",
    "ADZUNA_APP_ID": "adzuna-app-id",
    "ADZUNA_APP_KEY": "adzuna-app-key",
    "CAREERJET_AFFID": "careerjet-affid",
    "HIMALAYAS_API_KEY": "himalayas-api-key",
}


def spec(env: dict[str, str | None], gmail_token: str | None, environment_id: str, location: str,
         image: str = IMAGE, cron: str = CRON) -> dict:
    if not env.get("JOBSEARCH_PG_URL"):
        raise click.ClickException("JOBSEARCH_PG_URL isn't in .env")
    secrets, env_vars = [], []
    for name, secret in SECRETS.items():
        if env.get(name):
            secrets.append({"name": secret, "value": env[name]})
            env_vars.append({"name": name, "secretRef": secret})
    if gmail_token:
        json.loads(gmail_token)  # a broken token.json fails here, not in Azure
        secrets.append({"name": "gmail-token", "value": gmail_token})
        env_vars.append({"name": "GMAIL_TOKEN_JSON", "secretRef": "gmail-token"})
    return {
        "location": location,
        "properties": {
            "environmentId": environment_id,
            "configuration": {
                "triggerType": "Schedule",
                "scheduleTriggerConfig": {"cronExpression": cron, "parallelism": 1, "replicaCompletionCount": 1},
                # A full scrape takes about 10 minutes. No retries: a failed morning run is
                # covered by the desktop, whose tailoring run scrapes when this one didn't.
                "replicaTimeout": 3600,
                "replicaRetryLimit": 0,
                "secrets": secrets,
            },
            "template": {
                "containers": [{
                    "name": "scrape",
                    "image": image,
                    # Inside the Consumption plan's monthly free grant (docs/azure-scrape-job.md).
                    "resources": {"cpu": 1.0, "memory": "2Gi"},
                    "env": env_vars,
                }],
            },
        },
    }


@click.command()
@click.option("--environment-id", required=True, help="az containerapp env show ... --query id -o tsv")
@click.option("--location", default="canadacentral", show_default=True)
@click.option("--image", default=IMAGE, show_default=True)
@click.option("--cron", default=CRON, show_default=True, help="UTC")
@click.option("--out", "out_path", type=click.Path(path_type=Path), required=True)
def main(environment_id: str, location: str, image: str, cron: str, out_path: Path) -> None:
    env = dotenv_values(ROOT / ".env")
    token = ROOT / "token.json"
    body = spec(env, token.read_text(encoding="utf-8") if token.exists() else None,
                environment_id, location, image, cron)
    out_path.write_text(json.dumps(body), encoding="utf-8")
    names = [s["name"] for s in body["properties"]["configuration"]["secrets"]]
    click.echo(f"Job definition written with secrets: {', '.join(names)}", err=True)
    if "gmail-token" not in names:
        click.echo("No token.json: the job won't read alert emails.", err=True)


if __name__ == "__main__":
    sys.exit(main())
