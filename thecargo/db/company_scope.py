from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from thecargo.context import ANY_COMPANY, active_company
from thecargo.models.base import CompanyScoped


def _only(company_id):
    if company_id is None:
        return with_loader_criteria(CompanyScoped, lambda cls: cls.company_id.is_(None), include_aliases=True)
    return with_loader_criteria(CompanyScoped, lambda cls: cls.company_id == company_id, include_aliases=True)


def _scope_statement(state: ORMExecuteState) -> None:
    company_id = active_company()
    if company_id is ANY_COMPANY or state.is_column_load or state.is_relationship_load:
        return
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(_only(company_id))


def _stamp_new_rows(session: Session, flush_context, instances) -> None:
    company_id = active_company()
    if company_id is ANY_COMPANY or company_id is None:
        return
    for row in session.new:
        if isinstance(row, CompanyScoped) and row.company_id is None:
            row.company_id = company_id


def install_company_scope(session_class: type[Session] = Session) -> None:
    """Keep every ORM statement of this service inside the active company.

    A service calls this once. From then on a SELECT, UPDATE or DELETE that touches a
    `CompanyScoped` model reads the active company from the request (joins, aliases and
    subqueries included), and a new `CompanyScoped` row is filed under it. With nobody
    signed in the active company is `ANY_COMPANY` and nothing is added, so a webhook or a
    task narrows itself with `as_company(...)` once it knows whose work it is doing.

    Not reached: a subquery that names the model only in its WHERE, such as
    `select(1).where(Model.x == ...)`; give it `select_from(Model)`. A Core `insert()`
    skips the flush, so it sets `company_id` itself.
    """
    if event.contains(session_class, "do_orm_execute", _scope_statement):
        return
    event.listen(session_class, "do_orm_execute", _scope_statement)
    event.listen(session_class, "before_flush", _stamp_new_rows)


def uninstall_company_scope(session_class: type[Session] = Session) -> None:
    if event.contains(session_class, "do_orm_execute", _scope_statement):
        event.remove(session_class, "do_orm_execute", _scope_statement)
        event.remove(session_class, "before_flush", _stamp_new_rows)
