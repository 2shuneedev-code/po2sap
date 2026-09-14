"""HTTP 라우트. 계약은 contracts/api-contract.md 가 원천이다."""

from .routes_brands import router as brands_router

__all__ = ["brands_router"]
