from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.services.credit_service import CreditService


@pytest.mark.asyncio
async def test_credit_check_rejects_insufficient_balance_without_dev_refill(monkeypatch):
    subscription = {"credits_remaining": 2}
    monkeypatch.setattr(
        CreditService,
        "get_or_create_subscription",
        AsyncMock(return_value=subscription),
    )
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await CreditService.check_credits(db, "user-1", "ai_post")

    assert exc_info.value.status_code == 402
    db.__getitem__.assert_not_called()


def test_unknown_credit_action_is_not_silently_charged_one_credit():
    with pytest.raises(HTTPException) as exc_info:
        CreditService._get_action_cost("unconfigured_ai_feature")

    assert exc_info.value.status_code == 409
