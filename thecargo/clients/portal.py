import os
from uuid import UUID

from thecargo.clients.service import ServiceClient


class PortalClient(ServiceClient):
    def __init__(self, base_url: str | None = None, **kwargs):
        super().__init__(
            base_url or os.environ.get("AUTH_URL") or os.environ.get("AUTH_SERVICE_URL", "http://localhost:8000"),
            **kwargs,
        )

    async def account_customers(self, account_id: UUID) -> list[str]:
        data = await self.get(f"/api/internal/portal/accounts/{account_id}/customers")
        return data.get("customer_ids", [])

    async def customer_accounts(self, customer_id: UUID) -> list[str]:
        data = await self.get(f"/api/internal/portal/customers/{customer_id}/accounts")
        return data.get("account_ids", [])

    async def customer_states(self, org_id: UUID, customer_ids: list[UUID]) -> dict[str, dict]:
        data = await self.post(
            "/api/internal/portal/customers/status",
            {"organization_id": str(org_id), "customer_ids": [str(cid) for cid in customer_ids]},
        )
        return data.get("states", {})
