import pytest

from app.modules.billing import service
from app.modules.billing.models import CreditReservation


@pytest.mark.asyncio
async def test_metered_operation_id_fits_credit_reservation_task_id(monkeypatch) -> None:
    settled_task_ids: list[str] = []

    async def fake_reserve(*_args, **_kwargs) -> str:
        return "reservation-id"

    async def fake_settle(_db, _reservation_id: str, task_id: str, *, step: str) -> int:
        settled_task_ids.append(task_id)
        return 1

    async def fake_recover(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(service, "reserve_metered_operation", fake_reserve)
    monkeypatch.setattr(service, "settle_reservation", fake_settle)
    monkeypatch.setattr(service, "recover_reservation_after_failure", fake_recover)

    async with service.metered_operation(None, "user-id", "quote-id", "asr", {"seconds": 1}) as operation_id:
        task_id_limit = CreditReservation.__table__.c.task_id.type.length
        assert len(operation_id) <= task_id_limit

    assert settled_task_ids == [operation_id]
