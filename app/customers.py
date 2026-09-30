"""Customer catalog and Azure Blob container naming."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CustomerProfile:
    """Describe one sample customer tenant."""

    id: str
    name: str
    container: str
    accent: str
    default_retention_days: int = 90

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-compatible customer profile."""
        return asdict(self)


CUSTOMERS = (
    CustomerProfile("apple", "Apple", "cust-apple", "#555555"),
    CustomerProfile("microsoft", "Microsoft", "cust-microsoft", "#0078d4"),
    CustomerProfile("alphabet", "Alphabet", "cust-alphabet", "#4285f4"),
    CustomerProfile("amazon", "Amazon", "cust-amazon", "#ff9900"),
    CustomerProfile("nvidia", "NVIDIA", "cust-nvidia", "#76b900"),
    CustomerProfile("meta", "Meta", "cust-meta", "#0866ff"),
    CustomerProfile("tesla", "Tesla", "cust-tesla", "#cc0000"),
    CustomerProfile("broadcom", "Broadcom", "cust-broadcom", "#cc092f"),
    CustomerProfile("oracle", "Oracle", "cust-oracle", "#c74634"),
    CustomerProfile("salesforce", "Salesforce", "cust-salesforce", "#00a1e0"),
)

CUSTOMERS_BY_ID = {customer.id: customer for customer in CUSTOMERS}


def get_customer(customer_id: str) -> CustomerProfile | None:
    """Return a customer profile by stable identifier."""
    return CUSTOMERS_BY_ID.get(customer_id)


def list_customers() -> list[dict[str, str | int]]:
    """Return all customer profiles for API clients."""
    return [customer.to_dict() for customer in CUSTOMERS]