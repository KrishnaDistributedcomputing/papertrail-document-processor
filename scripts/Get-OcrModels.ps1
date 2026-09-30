#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Downloads verified open-source Tesseract OCR models.
.DESCRIPTION
    Downloads English recognition and orientation detection models from the
    official tessdata_best repository and validates their SHA-256 hashes.
.PARAMETER OutputDirectory
    Directory where traineddata files are stored.
.EXAMPLE
    ./scripts/Get-OcrModels.ps1
.NOTES
    The model files are distributed by the Tesseract project under Apache-2.0.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'models')
)

$ErrorActionPreference = 'Stop'

#region Functions

function Get-VerifiedModel {
    <#
    .SYNOPSIS
        Downloads and validates one OCR model.
    .OUTPUTS
        [System.IO.FileInfo] The verified model file.
    #>
    [CmdletBinding()]
    [OutputType([System.IO.FileInfo])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Sha256,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Destination
    )

    $ModelPath = Join-Path $Destination $Name
    $ModelUrl = "https://github.com/tesseract-ocr/tessdata_best/raw/refs/heads/main/$Name"
    Invoke-WebRequest -Uri $ModelUrl -OutFile $ModelPath
    $ActualHash = (Get-FileHash -Path $ModelPath -Algorithm SHA256).Hash
    if ($ActualHash -ne $Sha256) {
        Remove-Item -Path $ModelPath -Force
        throw "Checksum validation failed for $Name."
    }
    return Get-Item -Path $ModelPath
}

#endregion Functions

#region Main Execution

if ($MyInvocation.InvocationName -ne '.') {
    try {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
        $Models = @(
            Get-VerifiedModel -Name 'eng.traineddata' -Sha256 '8280AED0782FE27257A68EA10FE7EF324CA0F8D85BD2FD145D1C2B560BCB66BA' -Destination $OutputDirectory
            Get-VerifiedModel -Name 'osd.traineddata' -Sha256 '9CF5D576FCC47564F11265841E5CA839001E7E6F38FF7F7AACF46D15A96B00FF' -Destination $OutputDirectory
        )
        $Models | Select-Object Name, Length, LastWriteTime
        exit 0
    }
    catch {
        Write-Error -ErrorAction Continue "OCR model download failed: $($_.Exception.Message)"
        exit 1
    }
}

#endregion Main Execution