"""The /api/ask/stream wire format the UI parses: `stage` events as steps happen, then exactly one `result` or `error`."""

from __future__ import annotations

import asyncio
import json
import unittest
import unittest.mock

from backend.ask.contracts import AskRequest, AskResponse, StageEvent
from backend.ask.orchestrator import READ_ONLY
from backend.routers import ask as router
from backend.tests.test_ask import run


def stream(fake_run) -> list[dict]:
    class Fake:
        def __init__(self, on_event):
            self.on_event = on_event

        async def run(self, body: AskRequest) -> AskResponse:
            return await fake_run(self.on_event)

    async def collect() -> list[dict]:
        with unittest.mock.patch.object(router, "_orchestrator", lambda request, cancelled, on_event=None: Fake(on_event)):
            response = await router.ask_stream(AskRequest(question="q"), None)
            return [event async for event in response.body_iterator]
    return asyncio.run(collect())


class StreamFormatTests(unittest.TestCase):
    def test_stage_events_in_order_then_one_result(self):
        final, _, _ = run({}, question="Drop the first table in the schema.")

        async def ok(on_event):
            on_event(StageEvent(stage="context", status="running"))
            await asyncio.sleep(0)
            on_event(StageEvent(stage="context", status="succeeded", ms=3, detail="1 table"))
            return final
        events = stream(ok)
        self.assertEqual([e["event"] for e in events], ["stage", "stage", "result"])
        self.assertEqual(json.loads(events[0]["data"]), {"stage": "context", "status": "running", "ms": 0, "detail": ""})
        self.assertEqual(json.loads(events[1]["data"]), {"stage": "context", "status": "succeeded", "ms": 3, "detail": "1 table"})
        result = AskResponse.model_validate_json(events[2]["data"])
        self.assertEqual((result.status, result.kind, result.answer), ("ANSWERED", "chat", READ_ONLY))

    def test_a_crash_ends_with_one_error_event(self):
        async def boom(on_event):
            on_event(StageEvent(stage="context", status="running"))
            raise RuntimeError("warehouse unreachable")
        events = stream(boom)
        self.assertEqual([e["event"] for e in events], ["stage", "error"])
        self.assertTrue(json.loads(events[1]["data"])["message"].startswith("Something went wrong:"))


if __name__ == "__main__":
    unittest.main()
