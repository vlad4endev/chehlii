"""Паритет STATE_MAP MAX с Telegram / backend scenario names."""

from bots.core.scenario import (
    STATE_CLEAR,
    STATE_CONSULTING,
    STATE_WAITING_CONTACT,
    STATE_WAITING_MATERIALS,
    STATE_WAITING_NAME,
)
from bots.max.pending_fsm import _STATE_MAP, apply_pending_fsm
from bots.max.states import OrderFlow


def test_state_map_covers_guide_scenarios() -> None:
    assert _STATE_MAP[STATE_WAITING_CONTACT] == OrderFlow.waiting_contact
    assert _STATE_MAP[STATE_WAITING_NAME] == OrderFlow.waiting_name
    assert _STATE_MAP[STATE_WAITING_MATERIALS] == OrderFlow.waiting_materials
    assert _STATE_MAP[STATE_CONSULTING] == OrderFlow.consulting


class _FakeCtx:
    def __init__(self) -> None:
        self.state = None
        self.data: dict = {}

    async def clear(self) -> None:
        self.state = None
        self.data = {}

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **kwargs) -> dict:
        self.data.update(kwargs)
        return dict(self.data)


async def test_apply_pending_sets_order_and_state() -> None:
    ctx = _FakeCtx()
    await apply_pending_fsm(
        ctx, {"state": STATE_WAITING_NAME, "order_id": 42, "code": "msg_006а"}
    )
    assert ctx.state == OrderFlow.waiting_name
    assert ctx.data["order_id"] == 42


async def test_apply_pending_clear() -> None:
    ctx = _FakeCtx()
    ctx.state = OrderFlow.consulting
    ctx.data = {"order_id": 1}
    await apply_pending_fsm(ctx, {"state": STATE_CLEAR})
    assert ctx.state is None
    assert ctx.data == {}
