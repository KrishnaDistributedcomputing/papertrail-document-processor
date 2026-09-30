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
estimated_reading_time: 8
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
* At least 8 GB RAM and 10 GB free disk space for both local Qwen models,
  container images, and initial runtime data

The public web service listens on port `8081` by default. The API, queue, and
model services stay on private Docker networks.

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

The first deployment downloads the configured Qwen models through the
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