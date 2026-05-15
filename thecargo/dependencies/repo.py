"""Per-service ``get_repo()`` factory builder.

Each service holds its own ``get_db`` (the AsyncSession dependency wired to
that service's database). The repo factory is parameterised on it, so the
service stitches the two together once in its ``app/core/dependencies.py``
and routes pick up ``Depends(get_repo(<Repo>))`` instead of writing
``repo = <Repo>(db, org_id)`` inline.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.dependencies.auth import get_org_id

R = TypeVar("R")


def make_get_repo(get_db_dep: Callable[..., AsyncSession]) -> Callable[[type[R]], Callable[..., R]]:
    """Bind the project's repository pattern to a service's ``get_db``.

    Returns a callable ``get_repo(repo_cls)`` that produces a FastAPI
    dependency: it resolves the request session + ``org_id`` and
    instantiates the repo with both.

    Usage in a service::

        # app/core/dependencies.py
        from thecargo.dependencies.repo import make_get_repo
        from app.core.database import get_db
        get_repo = make_get_repo(get_db)

        # app/routes/v1/payments.py
        from app.core.dependencies import get_repo

        @router.get("")
        async def list_payments(
            repo: PaymentRepository = Depends(get_repo(PaymentRepository)),
        ):
            return await repo.list_all()
    """

    def get_repo(repo_cls: type[R]) -> Callable[..., R]:
        async def _dep(
            db: AsyncSession = Depends(get_db_dep),
            org_id: UUID = Depends(get_org_id),
        ) -> R:
            return repo_cls(db, org_id)

        _dep.__name__ = f"get_{repo_cls.__name__}"
        return _dep

    return get_repo
