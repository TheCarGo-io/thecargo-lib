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
