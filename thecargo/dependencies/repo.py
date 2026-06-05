from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.dependencies.auth import get_org_id

R = TypeVar("R")


def make_get_repo(get_db_dep: Callable[..., AsyncSession]) -> Callable[[type[R]], Callable[..., R]]:

    def get_repo(repo_cls: type[R]) -> Callable[..., R]:
        async def _dep(
            db: AsyncSession = Depends(get_db_dep),
            org_id: UUID = Depends(get_org_id),
        ) -> R:
            return repo_cls(db, org_id)

        _dep.__name__ = f"get_{repo_cls.__name__}"
        return _dep

    return get_repo
