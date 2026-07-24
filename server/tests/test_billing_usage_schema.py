from app.modules.billing.models import QuotaUsage
from app.modules.catalog.service import MODULE_BILLING_UNITS


def test_quota_usage_step_can_store_every_billable_module() -> None:
    step_limit = QuotaUsage.__table__.c.step.type.length

    assert all(len(module) <= step_limit for module in MODULE_BILLING_UNITS)
