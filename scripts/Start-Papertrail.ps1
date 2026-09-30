#!/usr/bin/env pwsh
#Requires -Version 7.0

<#
.SYNOPSIS
    Installs and starts Papertrail with Docker.
.DESCRIPTION
    Checks Docker, downloads Papertrail when run remotely, prefers published
    images, falls back to building the public source, waits for service health,
    and opens the portal. Existing Docker volumes are preserved on every run.
.PARAMETER InstallDirectory
    Directory used for a remote installation. A local repository is used when
    the script runs from one.
.PARAMETER SourceBuild
    Builds the application images from source without trying published images.
.PARAMETER NoBrowser
    Starts Papertrail without opening the portal in the default browser.
.EXAMPLE
    ./scripts/Start-Papertrail.ps1
.EXAMPLE
    irm https://raw.githubusercontent.com/KrishnaDistributedcomputing/papertrail-document-processor/main/scripts/Start-Papertrail.ps1 | iex
.NOTES
    Docker Desktop or Docker Engine with Compose v2 must already be running.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$InstallDirectory,

    [Parameter(Mandatory = $false)]
    [switch]$SourceBuild,

    [Parameter(Mandatory = $false)]
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

#region Functions

function Resolve-PapertrailRoot {
    <#
    .SYNOPSIS
        Resolves the local or managed Papertrail directory.
    .OUTPUTS
        [string] The absolute Papertrail directory.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $false)]
        [string]$RequestedDirectory
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedDirectory)) {
        return [System.IO.Path]::GetFullPath($RequestedDirectory)
    }

    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $LocalRoot = Split-Path $PSScriptRoot -Parent
        if (Test-Path (Join-Path $LocalRoot 'compose.yaml')) {
            return $LocalRoot
        }
    }

    return Join-Path $HOME '.papertrail'
}

function Assert-DockerReady {
    <#
    .SYNOPSIS
        Verifies that Docker Engine and Docker Compose v2 are available.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param()

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker is not installed. Install and start Docker Desktop, then run this command again.'
    }

    & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker is installed but is not running. Start Docker Desktop, then run this command again.'
    }

    & docker compose version --short 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose v2 is required. Update Docker Desktop or install the Docker Compose plugin.'
    }
}

function Install-PapertrailSource {
    <#
    .SYNOPSIS
        Downloads the public Papertrail source archive when it is not present.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Destination
    )

    if (Test-Path (Join-Path $Destination 'compose.yaml')) {
        return
    }

    if ((Test-Path $Destination) -and
        (Get-ChildItem -LiteralPath $Destination -Force | Select-Object -First 1)) {
        throw "The installation directory is not empty: $Destination"
    }

    Write-Host "Downloading Papertrail to $Destination ..." -ForegroundColor Cyan
    $TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "papertrail-$([guid]::NewGuid())"
    $ArchivePath = Join-Path $TemporaryDirectory 'papertrail.zip'
    $ArchiveUrl = 'https://github.com/KrishnaDistributedcomputing/papertrail-document-processor/archive/refs/heads/main.zip'

    try {
        New-Item -ItemType Directory -Path $TemporaryDirectory -Force | Out-Null
        Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ArchivePath
        Expand-Archive -Path $ArchivePath -DestinationPath $TemporaryDirectory

        $SourceRoot = Get-ChildItem -Path $TemporaryDirectory -Directory |
            Where-Object { Test-Path (Join-Path $_.FullName 'compose.yaml') } |
            Select-Object -First 1
        if (-not $SourceRoot) {
            throw 'The downloaded archive does not contain a Papertrail deployment.'
        }

        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Get-ChildItem -LiteralPath $SourceRoot.FullName -Force |
            Copy-Item -Destination $Destination -Recurse -Force
    }
    finally {
        Remove-Item -Path $TemporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Compose {
    <#
    .SYNOPSIS
        Runs Docker Compose from the Papertrail project directory.
    .OUTPUTS
        None.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$ProjectDirectory,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Manifest,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $false)]
        [switch]$AllowFailure
    )

    Push-Location $ProjectDirectory
    try {
        if ($AllowFailure) {
            & docker compose -f $Manifest @Arguments *> $null
        }
        else {
            & docker compose -f $Manifest @Arguments
        }
        $script:LastComposeExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if (($script:LastComposeExitCode -ne 0) -and -not $AllowFailure) {
        throw "Docker Compose failed with exit code $script:LastComposeExitCode."
    }
}

function Get-PapertrailUrl {
    <#
    .SYNOPSIS
        Gets the host URL published by the running web service.
    .OUTPUTS
        [uri] The local Papertrail URL.
    #>
    [CmdletBinding()]
    [OutputType([uri])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$ProjectDirectory,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Manifest
    )

    Push-Location $ProjectDirectory
    try {
        $PortOutput = & docker compose -f $Manifest port web 8080 2>$null | Select-Object -First 1
    }
    finally {
        Pop-Location
    }

    if (($LASTEXITCODE -ne 0) -or ($PortOutput -notmatch ':(\d+)$')) {
        throw 'Papertrail started, but its published web port could not be determined.'
    }
    return [uri]"http://localhost:$($Matches[1])"
}

#endregion Functions

#region Main Execution

if ($MyInvocation.InvocationName -ne '.') {
    $OriginalApiImage = [Environment]::GetEnvironmentVariable('PAPERTRAIL_API_IMAGE', 'Process')
    $OriginalWebImage = [Environment]::GetEnvironmentVariable('PAPERTRAIL_WEB_IMAGE', 'Process')
    $PublishedEnvironmentApplied = $false
    try {
        $ProjectDirectory = Resolve-PapertrailRoot -RequestedDirectory $InstallDirectory
        Assert-DockerReady
        Install-PapertrailSource -Destination $ProjectDirectory

        $SourceManifest = 'compose.yaml'
        $PublishedManifest = 'compose.deploy.yaml'
        $ActiveManifest = $SourceManifest
        $UsePublishedImages = -not $SourceBuild

        if ($UsePublishedImages) {
            $env:PAPERTRAIL_API_IMAGE = 'ghcr.io/krishnadistributedcomputing/papertrail-document-processor-api:latest'
            $env:PAPERTRAIL_WEB_IMAGE = 'ghcr.io/krishnadistributedcomputing/papertrail-document-processor-web:latest'
            $PublishedEnvironmentApplied = $true
            Write-Host 'Checking published application images ...' -ForegroundColor Cyan
            Invoke-Compose -ProjectDirectory $ProjectDirectory -Manifest $PublishedManifest -Arguments @('config', '--quiet')
            Invoke-Compose -ProjectDirectory $ProjectDirectory -Manifest $PublishedManifest -Arguments @('pull', '--quiet', 'web', 'api', 'worker') -AllowFailure
            if ($script:LastComposeExitCode -eq 0) {
                $ActiveManifest = $PublishedManifest
            }
            else {
                Write-Host 'Published images are unavailable. Building from public source instead ...' -ForegroundColor Yellow
                [Environment]::SetEnvironmentVariable('PAPERTRAIL_API_IMAGE', $OriginalApiImage, 'Process')
                [Environment]::SetEnvironmentVariable('PAPERTRAIL_WEB_IMAGE', $OriginalWebImage, 'Process')
                $PublishedEnvironmentApplied = $false
            }
        }

        if ($ActiveManifest -eq $SourceManifest) {
            Invoke-Compose -ProjectDirectory $ProjectDirectory -Manifest $SourceManifest -Arguments @('config', '--quiet')
            Write-Host 'Building and starting Papertrail ...' -ForegroundColor Cyan
            Invoke-Compose -ProjectDirectory $ProjectDirectory -Manifest $SourceManifest -Arguments @('up', '--detach', '--build', '--wait', '--remove-orphans')
        }
        else {
            Write-Host 'Starting Papertrail from published images ...' -ForegroundColor Cyan
            Invoke-Compose -ProjectDirectory $ProjectDirectory -Manifest $PublishedManifest -Arguments @('up', '--detach', '--wait', '--remove-orphans')
        }

        $PortalUrl = Get-PapertrailUrl -ProjectDirectory $ProjectDirectory -Manifest $ActiveManifest
        Invoke-WebRequest -Uri ([uri]::new($PortalUrl, '/api/v1/health/live')) -TimeoutSec 10 | Out-Null

        Write-Host ''
        Write-Host "Papertrail is ready: $PortalUrl" -ForegroundColor Green
        Write-Host "Installation: $ProjectDirectory"
        Write-Host 'Run this launcher again at any time to start or repair the deployment.'

        if (-not $NoBrowser) {
            try {
                Start-Process $PortalUrl.AbsoluteUri
            }
            catch {
                Write-Warning "The browser could not be opened automatically. Open $PortalUrl"
            }
        }
    }
    catch {
        throw "Papertrail deployment failed: $($_.Exception.Message)"
    }
    finally {
        if ($PublishedEnvironmentApplied) {
            [Environment]::SetEnvironmentVariable('PAPERTRAIL_API_IMAGE', $OriginalApiImage, 'Process')
            [Environment]::SetEnvironmentVariable('PAPERTRAIL_WEB_IMAGE', $OriginalWebImage, 'Process')
        }
    }
}

#endregion Main Execution
