import os
from uuid import UUID

from thecargo.clients.service import ServiceClient


class ShipmentClient(ServiceClient):
    def __init__(self, base_url: str | None = None, **kwargs):
        super().__init__(
            base_url or os.environ.get("SHIPMENT_URL", "http://localhost:8001"),
            **kwargs,
        )

    async def customer(self, customer_id: UUID) -> dict:
        return await self.get(f"/api/internal/customers/{customer_id}")

    async def shipment_owner(self, shipment_id: UUID) -> dict:
        return await self.get(f"/api/internal/shipments/{shipment_id}/owner")

    async def customers_by_email(self, organization_id: UUID, email: str, limit: int = 200) -> list[dict]:
        data = await self.get(
            "/api/internal/customers",
            params={
                "organization_id": str(organization_id),
                "email": email,
                "with_count": "false",
                "limit": limit,
            },
        )
        return data.get("results", [])
