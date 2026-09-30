"""Persist customer documents in private Azure Blob containers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.storage.models import (
    ManagementPolicy,
    ManagementPolicyRule,
    ManagementPolicySchema,
)
from azure.storage.blob import BlobServiceClient, ContentSettings

from app.config import settings
from app.customers import CUSTOMERS, CustomerProfile


class CloudStorageError(RuntimeError):
    """Raised when configured Azure storage cannot complete an operation."""


def is_configured() -> bool:
    """Return whether cloud persistence has credentials."""
    return settings.azure_storage_enabled


def is_management_configured() -> bool:
    """Return whether Azure lifecycle policy management has resource settings."""
    return settings.azure_management_enabled


def _connection_string() -> str:
    if not settings.azure_storage_connection_string:
        raise CloudStorageError("Azure storage is not configured.")
    value = settings.azure_storage_connection_string.get_secret_value()
    if not value:
        raise CloudStorageError("Azure storage is not configured.")
    return value


def _blob_paths(document_id: str) -> tuple[str, str]:
    date_path = datetime.now(UTC).strftime("%Y/%m")
    return (
        f"source/{date_path}/{document_id}.pdf",
        f"results/{date_path}/{document_id}.json",
    )


def build_retention_rule(
    customer: CustomerProfile,
    retention_days: int,
) -> dict[str, Any]:
    """Build a lifecycle rule that deletes blobs after the customer duration."""
    return {
        "enabled": True,
        "name": f"papertrail-{customer.id}-retention",
        "type": "Lifecycle",
        "definition": {
            "actions": {
                "baseBlob": {
                    "delete": {"daysAfterModificationGreaterThan": retention_days},
                }
            },
            "filters": {
                "blobTypes": ["blockBlob"],
                "prefixMatch": [f"{customer.container}/"],
            },
        },
    }


def _management_client() -> StorageManagementClient:
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return StorageManagementClient(credential, settings.azure_subscription_id)


def sync_retention_policies(retention_days: dict[str, int]) -> int:
    """Replace Papertrail lifecycle rules while preserving unrelated account rules."""
    if not is_management_configured():
        return 0
    try:
        client = _management_client()
        policies = client.management_policies
        current = policies.get(
            settings.azure_resource_group,
            settings.azure_storage_account_name,
            "default",
        )
        existing_rules = list(current.policy.rules)
    except ResourceNotFoundError:
        existing_rules = []
    except Exception as error:
        raise CloudStorageError(f"Azure lifecycle policy read failed: {error}") from error

    owned_names = {f"papertrail-{customer.id}-retention" for customer in CUSTOMERS}
    merged_rules = [rule for rule in existing_rules if rule.name not in owned_names]
    merged_rules.extend(
        ManagementPolicyRule(
            **build_retention_rule(customer, retention_days[customer.id])
        )
        for customer in CUSTOMERS
    )
    policy = ManagementPolicy(policy=ManagementPolicySchema(rules=merged_rules))
    try:
        policies.create_or_update(
            settings.azure_resource_group,
            settings.azure_storage_account_name,
            "default",
            policy,
        )
    except Exception as error:
        raise CloudStorageError(f"Azure lifecycle policy update failed: {error}") from error
    return len(CUSTOMERS)


def planned_location(
    customer: CustomerProfile,
    document_id: str,
    retention_days: int,
) -> dict[str, Any]:
    """Return deterministic Blob destinations before uploading content."""
    source_blob, result_blob = _blob_paths(document_id)
    return {
        "provider": "azure_blob",
        "account": settings.azure_storage_account_name,
        "container": customer.container,
        "source_blob": source_blob,
        "result_blob": result_blob,
        "retention_days": retention_days,
        "retention_policy": "azure_lifecycle_management",
        "status": "pending" if is_configured() else "not_configured",
    }


def upload_document(
    *,
    customer: CustomerProfile,
    document_id: str,
    source_path: Path,
    result_json: bytes,
    retention_days: int,
    location: dict[str, Any],
) -> dict[str, Any]:
    """Upload source and result blobs governed by the account lifecycle policy."""
    connection_string = _connection_string()
    service = BlobServiceClient.from_connection_string(connection_string)
    container = service.get_container_client(customer.container)
    try:
        container.create_container(metadata={"customer": customer.id})
    except ResourceExistsError:
        pass

    metadata = {
        "customer": customer.id,
        "document_id": document_id,
        "retention_days": str(retention_days),
    }
    source_blob = str(location["source_blob"])
    result_blob = str(location["result_blob"])
    try:
        with source_path.open("rb") as source:
            container.upload_blob(
                source_blob,
                source,
                overwrite=True,
                metadata={**metadata, "artifact": "source"},
                content_settings=ContentSettings(content_type="application/pdf"),
            )
        container.upload_blob(
            result_blob,
            result_json,
            overwrite=True,
            metadata={**metadata, "artifact": "result"},
            content_settings=ContentSettings(content_type="application/json"),
        )
    except Exception as error:
        raise CloudStorageError(f"Azure Blob upload failed: {error}") from error
    return {
        **location,
        "retention_policy": "azure_lifecycle_management",
        "status": "stored",
    }


def container_usage(customer: CustomerProfile) -> dict[str, int]:
    """Return live blob counts and bytes for a customer container."""
    if not is_configured():
        return {"blob_count": 0, "source_count": 0, "result_count": 0, "bytes": 0}
    service = BlobServiceClient.from_connection_string(_connection_string())
    container = service.get_container_client(customer.container)
    usage = {"blob_count": 0, "source_count": 0, "result_count": 0, "bytes": 0}
    try:
        for blob in container.list_blobs():
            usage["blob_count"] += 1
            usage["bytes"] += max(0, int(blob.size or 0))
            if blob.name.startswith("source/"):
                usage["source_count"] += 1
            elif blob.name.startswith("results/"):
                usage["result_count"] += 1
    except Exception as error:
        raise CloudStorageError(f"Azure storage inventory failed: {error}") from error
    return usage