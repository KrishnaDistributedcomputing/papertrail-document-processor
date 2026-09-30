---
title: Papertrail Deployment Guide
description: Deploy Papertrail automatically or operate it directly with Docker Compose
author: Engineering
ms.date: 2026-09-30
ms.topic: how-to
keywords:
  - Docker Compose
  - GitHub Container Registry
  - deployment
  - Azure Blob Storage
estimated_reading_time: 12
---

## One-command deployment

Docker must be installed and running. The launcher handles everything else:
source download, image selection, source-build fallback, service startup,
health checks, and opening the portal.

On Windows, run this command in PowerShell 7:

```powershell
irm https://raw.githubusercontent.com/KrishnaDistributedcomputing/papertrail-document-processor/main/scripts/Start-Papertrail.ps1 | iex
```

On Linux or macOS, run:

```bash
curl -fsSL https://raw.githubusercontent.com/KrishnaDistributedcomputing/papertrail-document-processor/main/scripts/start-papertrail.sh | bash
```

No repository clone, `.env` file, Azure account, or registry login is required.
Remote installations are stored in `~/.papertrail`. The launcher first tries
the smaller image-only deployment. If the application packages are not
available to the current Docker client, it builds the same application from
the public source without prompting for credentials.

Running the launcher again is idempotent. Existing named volumes preserve
documents, generated JSON, SQLite history, Redis state, and downloaded Ollama
models across container replacement and deployment-mode changes.

## Deployment options

Papertrail runs as six Docker Compose services. Deploy it from source when the
host can build images, or use the image-only manifest with images published by
GitHub Actions.

| Option           | Manifest              | Use when                                           |
|------------------|-----------------------|----------------------------------------------------|
| Automatic        | Selected by launcher  | Installing with no application configuration       |
| Source build     | `compose.yaml`        | Developing locally or building on the host         |
| Published images | `compose.deploy.yaml` | Running images available to the Docker client      |

The deployment retains documents, generated JSON, SQLite history, Redis data,
and downloaded Ollama models in named Docker volumes.

## Prerequisites

Install the following software on the deployment host:

* Docker Engine or Docker Desktop with Docker Compose v2
* PowerShell 7 for the Windows launcher
* Bash, `curl`, and `tar` for the Linux and macOS launcher
* At least 8 GB RAM and 15 GB free disk space for the five default local models,
  container images, and initial runtime data

The public web service listens on port `8081` by default. The API, queue, and
model services stay on private Docker networks.

## Host on Azure

Use a single Ubuntu virtual machine for the current Papertrail architecture.
This preserves Docker Compose, CPU-local Ollama inference, SQLite, Redis, and
the three persistent named volumes. Azure App Service and Azure Container Apps
are not drop-in targets for this six-service manifest because the model cache,
queue, and document database require coordinated persistent storage.

### Recommended Azure configuration

| Resource             | Recommended baseline                         |
|----------------------|----------------------------------------------|
| Virtual machine      | `Standard_D4s_v5` (4 vCPU, 16 GB RAM)        |
| Operating system     | Ubuntu 22.04 LTS                              |
| OS disk              | 64 GB or larger Standard SSD                 |
| Managed identity     | System-assigned                              |
| Blob storage         | StorageV2 with `Standard_LRS`                |
| Inbound access       | SSH from an approved IP; HTTPS for users     |
| Papertrail port      | `8081`, kept private behind SSH or a proxy   |

Larger models and concurrent document processing benefit from additional CPU
and memory. Keep one application replica unless SQLite, Redis, and the named
volumes are replaced with shared production services.

### Create the Azure resources

Install the Azure CLI on your workstation, sign in, and run these commands in
PowerShell. The storage account suffix makes its globally unique name easier
to create. Replace `<approved-public-ip>` with your workstation's public IPv4
address before running the block; keep the `/32` suffix to allow only that
address to connect over SSH.

```powershell
az login

$ResourceGroup = "rg-papertrail-prod"
$Location = "eastus"
$VmName = "vm-papertrail-prod"
$AdminUser = "azureuser"
$ApprovedSshCidr = "<approved-public-ip>/32"
$NsgName = "nsg-$VmName"
$StorageAccount = "papertrail$((Get-Random -Minimum 100000 -Maximum 999999))"
$SubscriptionId = az account show --query id --output tsv

az group create --name $ResourceGroup --location $Location
az storage account create `
  --name $StorageAccount `
  --resource-group $ResourceGroup `
  --location $Location `
  --kind StorageV2 `
  --sku Standard_LRS `
  --https-only true `
  --min-tls-version TLS1_2 `
  --allow-blob-public-access false

az network nsg create `
  --resource-group $ResourceGroup `
  --name $NsgName `
  --location $Location
az network nsg rule create `
  --resource-group $ResourceGroup `
  --nsg-name $NsgName `
  --name AllowApprovedSsh `
  --priority 100 `
  --access Allow `
  --direction Inbound `
  --protocol Tcp `
  --source-address-prefixes $ApprovedSshCidr `
  --destination-port-ranges 22

az vm create `
  --resource-group $ResourceGroup `
  --name $VmName `
  --location $Location `
  --image Ubuntu2204 `
  --size Standard_D4s_v5 `
  --admin-username $AdminUser `
  --generate-ssh-keys `
  --os-disk-size-gb 64 `
  --storage-sku StandardSSD_LRS `
  --public-ip-sku Standard `
  --nsg $NsgName `
  --nsg-rule NONE `
  --assign-identity

$PrincipalId = az vm identity show `
  --resource-group $ResourceGroup `
  --name $VmName `
  --query principalId `
  --output tsv
$StorageId = az storage account show `
  --resource-group $ResourceGroup `
  --name $StorageAccount `
  --query id `
  --output tsv
$ResourceGroupId = az group show `
  --name $ResourceGroup `
  --query id `
  --output tsv
$LifecycleRoleName = "Papertrail Lifecycle Manager $ResourceGroup"
$LifecycleRoleFile = Join-Path $env:TEMP "papertrail-lifecycle-role.json"
@{
  Name = $LifecycleRoleName
  Description = "Read and update Papertrail Blob lifecycle policies"
  Actions = @(
    "Microsoft.Storage/storageAccounts/read"
    "Microsoft.Storage/storageAccounts/managementPolicies/read"
    "Microsoft.Storage/storageAccounts/managementPolicies/write"
  )
  NotActions = @()
  DataActions = @()
  NotDataActions = @()
  AssignableScopes = @($ResourceGroupId)
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $LifecycleRoleFile

az role definition create --role-definition $LifecycleRoleFile
Remove-Item $LifecycleRoleFile

az role assignment create `
  --assignee-object-id $PrincipalId `
  --assignee-principal-type ServicePrincipal `
  --role $LifecycleRoleName `
  --scope $StorageId

$PublicIp = az vm show `
  --resource-group $ResourceGroup `
  --name $VmName `
  --show-details `
  --query publicIps `
  --output tsv

[pscustomobject]@{
  PublicIp = $PublicIp
  ApprovedSshCidr = $ApprovedSshCidr
  StorageAccount = $StorageAccount
  SubscriptionId = $SubscriptionId
}
```

The VM identity receives only storage-account read and lifecycle-policy
read/write actions. The operator account creates the custom role and retrieves
the connection string. Creating custom roles and role assignments requires
Owner or User Access Administrator permissions. Role propagation can take
several minutes.

### Install Papertrail on the VM

Connect to the VM, install Docker Engine and the Azure CLI, then reconnect so
the Docker group membership takes effect:

```powershell
ssh "$AdminUser@$PublicIp"
```

```bash
sudo apt-get update
sudo apt-get install --yes ca-certificates curl
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sudo sh /tmp/get-docker.sh
rm /tmp/get-docker.sh
sudo usermod --append --groups docker "$USER"
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
exit
```

Reconnect, authenticate with the VM identity, and run the standard launcher:

```powershell
ssh "$AdminUser@$PublicIp"
```

```bash
az login --identity
curl -fsSL https://raw.githubusercontent.com/KrishnaDistributedcomputing/papertrail-document-processor/main/scripts/start-papertrail.sh | bash -s -- --no-browser
cd ~/.papertrail
cp .env.example .env
```

Set the Azure values created earlier. Replace the angle-bracket placeholders
with the values printed by the resource creation commands.

```bash
export AZURE_SUBSCRIPTION_ID="<subscription-id>"
export AZURE_RESOURCE_GROUP="rg-papertrail-prod"
export AZURE_STORAGE_ACCOUNT_NAME="<storage-account-name>"
export AZURE_STORAGE_REGION="eastus"

sed -i \
  -e "s|^AZURE_SUBSCRIPTION_ID=.*|AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID}|" \
  -e "s|^AZURE_RESOURCE_GROUP=.*|AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP}|" \
  -e "s|^AZURE_STORAGE_ACCOUNT_NAME=.*|AZURE_STORAGE_ACCOUNT_NAME=${AZURE_STORAGE_ACCOUNT_NAME}|" \
  -e "s|^AZURE_STORAGE_REGION=.*|AZURE_STORAGE_REGION=${AZURE_STORAGE_REGION}|" \
  -e "s|^AZURE_MANAGEMENT_IDENTITY_ENABLED=.*|AZURE_MANAGEMENT_IDENTITY_ENABLED=true|" \
  .env
```

From the workstation PowerShell session that created the resources, retrieve
the connection string with your operator identity and send it directly to the
protected secret file. The value is not granted to the VM identity.

```powershell
$ConnectionString = az storage account show-connection-string `
  --subscription $SubscriptionId `
  --resource-group $ResourceGroup `
  --name $StorageAccount `
  --query connectionString `
  --output tsv
$SecretLine = "AZURE_STORAGE_CONNECTION_STRING=$ConnectionString"
$SecretLine | ssh "$AdminUser@$PublicIp" `
  'umask 077; mkdir -p ~/.papertrail/.secrets; cat > ~/.papertrail/.secrets/azure.env; chmod 600 ~/.papertrail/.secrets/azure.env'
$ConnectionString = $null
$SecretLine = $null
```

Return to the VM session and apply the configuration:

```bash
cd ~/.papertrail
./scripts/start-papertrail.sh --no-browser
```

The connection string enables source and result uploads. The managed identity
enables lifecycle policy updates from the retention controls in Papertrail.

### Access and validate the Azure host

Keep port `8081` closed to the internet during initial validation. From your
workstation, create an SSH tunnel and leave the command running:

```powershell
ssh -L 8081:127.0.0.1:8081 "$AdminUser@$PublicIp"
```

Open <http://localhost:8081>, then verify service and API health on the VM:

```bash
cd ~/.papertrail
docker compose ps
curl --fail http://127.0.0.1:8081/api/v1/health/live
```

> [!IMPORTANT]
> Papertrail does not provide user authentication. For shared or production
> access, keep `8081` private and place an authenticated TLS reverse proxy,
> VPN, or managed ingress in front of it. Allow only ports `80` and `443` from
> the required client networks, and restrict SSH to approved source addresses.

Back up or snapshot the VM disk as well as Azure Blob Storage. Blob persistence
contains source PDFs and result JSON, while SQLite history, Redis state, and
the downloaded Ollama models remain in Docker volumes on the VM disk.

## Run from a clone

The launchers detect and use an existing repository clone:

```powershell
git clone https://github.com/KrishnaDistributedcomputing/papertrail-document-processor.git
Set-Location papertrail-document-processor
./scripts/Start-Papertrail.ps1
```

On Linux or macOS, run `./scripts/start-papertrail.sh` after cloning. Use
`-SourceBuild` in PowerShell or `--source` in Bash to build locally without
checking published images.

No configuration file is required. To customize the deployment, create one
from the supplied example:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`, `.secrets/`, uploaded documents, database files, or
backups. The repository ignore rules exclude these paths.

The default resource names are suitable for a single Papertrail installation:

```dotenv
WEB_PORT=8081
PAPERTRAIL_DOCUMENT_VOLUME=papertrail_document-data
PAPERTRAIL_REDIS_VOLUME=papertrail_redis-data
PAPERTRAIL_OLLAMA_VOLUME=papertrail_ollama-data
```

## Deploy from source

The repository includes the verified OCR model files and vendored Python
packages needed by the offline application image build. Run this command only
when bypassing the launcher:

```powershell
docker compose up --detach --build --wait
```

The first deployment downloads the configured Ollama models through the
one-shot `ollama-model` service. This can take several minutes. Later starts
reuse the `papertrail_ollama-data` volume.

## Deploy published GitHub images directly

The `Test and publish container images` workflow tests the project and
publishes API and web images to GitHub Container Registry after changes reach
`main`. Version tags such as `v1.0.0` produce matching immutable image tags.

Direct image deployment requires the packages to be anonymously readable or
the Docker client to already have GitHub Container Registry access. The
automatic launcher does not require this access because it falls back to a
source build.

For a restricted package, create a GitHub personal access token with
`read:packages`, place it in the current shell, and authenticate Docker. Do not
write the token to project files.

```powershell
$env:GHCR_TOKEN | docker login ghcr.io --username KrishnaDistributedcomputing --password-stdin
```

The image-only manifest already defaults to the `latest` API and web packages.
Pull and start it with:

```powershell
docker compose -f compose.deploy.yaml pull
docker compose -f compose.deploy.yaml up --detach --wait
```

For repeatable production deployment, set `PAPERTRAIL_API_IMAGE` and
`PAPERTRAIL_WEB_IMAGE` in `.env` to release tags such as `v1.0.0`.

## Configure Azure storage

Papertrail runs without Azure credentials and reports local storage estimates.
To persist source PDFs and result JSON in private customer containers, create
the ignored secret file `.secrets/azure.env`:

```dotenv
AZURE_STORAGE_CONNECTION_STRING=<storage-account-connection-string>
```

Set the non-secret Azure values in `.env`:

```dotenv
AZURE_STORAGE_ACCOUNT_NAME=<storage-account-name>
AZURE_SUBSCRIPTION_ID=<subscription-id>
AZURE_RESOURCE_GROUP=<resource-group>
AZURE_MANAGEMENT_IDENTITY_ENABLED=false
AZURE_STORAGE_REGION=eastus
AZURE_STORAGE_SKU=Standard_LRS
```

Both the API and worker receive `.secrets/azure.env`. The worker needs the
connection string to upload processed source and result blobs. Enable Azure
management identity only when the deployment environment supplies an identity
that can read and update storage lifecycle policies.

> [!IMPORTANT]
> Keep `.secrets/azure.env` outside source control. Rotate the storage key if it
> is exposed in a terminal transcript, issue, commit, or build log.

Restart the application after changing credentials:

```powershell
docker compose up --detach --force-recreate api worker
```

Use `-f compose.deploy.yaml` in that command when running published images.

## Validate the deployment

Inspect container health:

```powershell
docker compose ps
docker compose logs --tail 100 api worker web ollama
```

Check the public endpoints:

```powershell
Invoke-RestMethod http://localhost:8081/api/v1/health/live
Invoke-WebRequest http://localhost:8081/health -UseBasicParsing
```

Open these portal views:

* Processor: <http://localhost:8081>
* Token usage and cost: <http://localhost:8081/tokens>
* Technology: <http://localhost:8081/technology>
* LLM logic: <http://localhost:8081/logic>

For internet-facing use, place a TLS reverse proxy or managed ingress in front
of port `8081`. Restrict direct access to the Docker host with its firewall.

## Publish a release

Run the test suite before tagging a release:

```powershell
docker compose --profile test build test
docker compose --profile test run --rm test pytest -q
git tag v1.0.0
git push origin v1.0.0
```

The GitHub workflow publishes `v1.0.0` and `sha-*` tags for both images. Wait
for the workflow to complete before deploying the release tag.

## Upgrade or roll back

Update an image deployment after changing both image tags in `.env`:

```powershell
docker compose -f compose.deploy.yaml pull
docker compose -f compose.deploy.yaml up --detach --wait --remove-orphans
```

To roll back, set both image references to the previous version tag and run the
same two commands. Named volumes remain unchanged during container replacement.

## Back up persistent data

Stop database writers, archive the document volume, and restart the services:

```powershell
docker compose stop api worker
docker run --rm --volume papertrail_document-data:/data:ro --volume "${PWD}:/backup" alpine:3.21 tar -czf /backup/papertrail-document-data.tgz -C /data .
docker compose start api worker
```

Store the archive in a protected backup location. The `.gitignore` excludes
`*.tgz` files so a local backup is not added to Git accidentally.

## Stop or remove the deployment

Stop and remove containers while preserving data:

```powershell
docker compose down
```

Delete containers and all named-volume data only when permanent removal is
intended:

```powershell
docker compose down --volumes
```

Add `-f compose.deploy.yaml` to either command for an image-only deployment.