"""Tests for Azure Blob persistence and lifecycle retention policies."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app import cloud_storage
from app.config import settings
from app.customers import CUSTOMERS, CUSTOMERS_BY_ID


def test_uploads_source_and_result_without_per_blob_expiry(tmp_path: Path) -> None:
    source_path = tmp_path / "document.pdf"
    source_path.write_bytes(b"%PDF-test")
    customer = CUSTOMERS_BY_ID["apple"]
    location = {
        "provider": "azure_blob",
        "account": "stpapertrailtest",
        "container": customer.container,
        "source_blob": "source/2026/09/document-1.pdf",
        "result_blob": "results/2026/09/document-1.json",
        "retention_days": 30,
        "status": "pending",
    }
    service = MagicMock()

    with (
        patch.object(
            settings,
            "azure_storage_connection_string",
            SecretStr("UseDevelopmentStorage=true"),
        ),
        patch("app.cloud_storage.BlobServiceClient.from_connection_string", return_value=service),
    ):
        stored = cloud_storage.upload_document(
            customer=customer,
            document_id="document-1",
            source_path=source_path,
            result_json=b'{"status":"completed"}',
            retention_days=30,
            location=location,
        )

    container = service.get_container_client.return_value
    assert container.upload_blob.call_count == 2
    assert stored["status"] == "stored"
    assert stored["retention_policy"] == "azure_lifecycle_management"


def test_builds_customer_lifecycle_rule_from_retention_duration() -> None:
    rule = cloud_storage.build_retention_rule(CUSTOMERS_BY_ID["apple"], 30)

    assert rule == {
        "enabled": True,
        "name": "papertrail-apple-retention",
        "type": "Lifecycle",
        "definition": {
            "actions": {
                "baseBlob": {
                    "delete": {"daysAfterModificationGreaterThan": 30},
                }
            },
            "filters": {
                "blobTypes": ["blockBlob"],
                "prefixMatch": ["cust-apple/"],
            },
        },
    }


def test_syncs_all_customer_rules_and_preserves_unrelated_rules() -> None:
    external_rule = SimpleNamespace(name="external-archive-rule")
    replaced_rule = SimpleNamespace(name="papertrail-apple-retention")
    client = MagicMock()
    client.management_policies.get.return_value.policy.rules = [
        external_rule,
        replaced_rule,
    ]
    retention = {customer.id: 90 for customer in CUSTOMERS}
    retention["apple"] = 30

    with (
        patch.object(settings, "azure_subscription_id", "subscription-id"),
        patch.object(settings, "azure_resource_group", "rg-papertrail"),
        patch.object(settings, "azure_storage_account_name", "stpapertrailtest"),
        patch.object(settings, "azure_management_identity_enabled", True),
        patch("app.cloud_storage._management_client", return_value=client),
    ):
        updated = cloud_storage.sync_retention_policies(retention)

    assert updated == 10
    call = client.management_policies.create_or_update.call_args
    assert call.args[:3] == ("rg-papertrail", "stpapertrailtest", "default")
    rules = call.args[3].policy.rules
    assert rules[0] is external_rule
    papertrail_rules = {rule.name: rule.as_dict() for rule in rules[1:]}
    assert len(papertrail_rules) == 10
    assert papertrail_rules["papertrail-apple-retention"]["definition"]["actions"] == {
        "baseBlob": {"delete": {"daysAfterModificationGreaterThan": 30}}
    }


def test_wraps_lifecycle_policy_read_failures() -> None:
    client = MagicMock()
    client.management_policies.get.side_effect = RuntimeError("credential unavailable")
    retention = {customer.id: 90 for customer in CUSTOMERS}

    with (
        patch.object(settings, "azure_subscription_id", "subscription-id"),
        patch.object(settings, "azure_resource_group", "rg-papertrail"),
        patch.object(settings, "azure_storage_account_name", "stpapertrailtest"),
        patch.object(settings, "azure_management_identity_enabled", True),
        patch("app.cloud_storage._management_client", return_value=client),
        pytest.raises(cloud_storage.CloudStorageError, match="policy read failed"),
    ):
        cloud_storage.sync_retention_policies(retention)