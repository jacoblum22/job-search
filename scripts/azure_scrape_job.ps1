# The daily scrape as an Azure Container Apps job (Azure plan, phase 5; docs/azure-scrape-job.md).
# Run in normal PowerShell in the project folder, with the Azure CLI signed in.
#
#   .\scripts\azure_scrape_job.ps1 setup    # once: providers, Container Apps environment, Postgres rule
#   .\scripts\azure_scrape_job.ps1 deploy   # create or update the job (after changing .env or token.json too)
#   .\scripts\azure_scrape_job.ps1 run      # start one run now, outside the schedule
#   .\scripts\azure_scrape_job.ps1 status   # recent runs in Azure, and what the last scrape did

param(
    [Parameter(Mandatory = $true)][ValidateSet("setup", "deploy", "run", "status")][string]$Step
)

$ErrorActionPreference = "Stop"
$rg = "rg-job-search"
$location = "canadacentral"
$envName = "cae-job-search"
$job = "job-search-scrape"
$pgServer = "jobsearch-pg-jake"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

switch ($Step) {
    "setup" {
        az extension add --name containerapp --upgrade --yes --only-show-errors; Check "containerapp extension"
        # A new subscription registers each provider once (MissingSubscriptionRegistration otherwise).
        az provider register --namespace Microsoft.App --wait; Check "register Microsoft.App"
        az provider register --namespace Microsoft.OperationalInsights --wait; Check "register Microsoft.OperationalInsights"
        # Consumption-only environment: no charge of its own. Its logs go to a Log Analytics
        # workspace it creates (first 5 GB a month free; a run logs well under 1 MB).
        $null = az containerapp env create --name $envName --resource-group $rg --location $location `
            --logs-destination log-analytics --only-show-errors; Check "containerapp env create"
        # Container Apps on the Consumption plan has no fixed outbound IP, so Postgres admits
        # Azure's own address range (the 0.0.0.0 rule); the password and TLS still guard it.
        $null = az postgres flexible-server firewall-rule create --resource-group $rg --server-name $pgServer `
            --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0; Check "firewall rule"
        az postgres flexible-server firewall-rule list --resource-group $rg --server-name $pgServer -o table
        Write-Host "Setup done. Next: .\scripts\azure_scrape_job.ps1 deploy"
    }
    "deploy" {
        . (Join-Path $PSScriptRoot "uv_path.ps1")
        if (-not (Add-UvToPath)) { throw "uv not found" }
        # The scoring files must be in Postgres before the job's first run (src/score_inputs.py).
        uv run python scripts/score_inputs.py push; Check "score_inputs push"
        $envId = az containerapp env show --name $envName --resource-group $rg --query id -o tsv; Check "env show"
        $sub = az account show --query id -o tsv; Check "account show"
        # The definition holds the secrets: a temp file, deleted whatever happens.
        $spec = Join-Path $env:TEMP "job-search-scrape-spec.json"
        try {
            uv run python scripts/azure_job_spec.py --environment-id $envId --location $location --out $spec
            Check "azure_job_spec"
            $url = "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.App/jobs/${job}?api-version=2024-03-01"
            # $null =: the reply echoes the secrets back.
            $null = az rest --method put --url $url --body "@$spec"; Check "az rest put"
        } finally {
            Remove-Item $spec -ErrorAction SilentlyContinue
        }
        az containerapp job show --name $job --resource-group $rg `
            --query "{state:properties.provisioningState, cron:properties.configuration.scheduleTriggerConfig.cronExpression, image:properties.template.containers[0].image}" -o table
    }
    "run" {
        az containerapp job start --name $job --resource-group $rg --query name -o tsv; Check "job start"
        Write-Host "Started. A full scrape takes about 10 minutes; then: .\scripts\azure_scrape_job.ps1 status"
    }
    "status" {
        az containerapp job execution list --name $job --resource-group $rg `
            --query "[0:5].{run:name, status:properties.status, start:properties.startTime, end:properties.endTime}" -o table
        . (Join-Path $PSScriptRoot "uv_path.ps1")
        if (Add-UvToPath) { uv run python scripts/aggregate.py --show-last-run }
    }
}
