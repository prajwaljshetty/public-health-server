import asyncio
import logging
from collections import defaultdict
from typing import Any

from app.firebase import realtime_db


logger = logging.getLogger(__name__)


class HouseholdStatusHub:
    """Route one shared Firebase households listener to household WebSockets."""

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._states: dict[str, dict] = {}
        self._listener = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    async def start(self):
        if self._listener is not None:
            return

        self._loop = asyncio.get_running_loop()
        self._stopping = False
        households_reference = realtime_db.reference("households")

        def firebase_listener(event):
            if self._stopping or self._loop is None or self._loop.is_closed():
                return
            future = asyncio.run_coroutine_threadsafe(
                self._handle_firebase_event(event),
                self._loop,
            )
            future.add_done_callback(self._report_callback_failure)

        self._listener = await asyncio.to_thread(
            households_reference.listen,
            firebase_listener,
        )

    async def stop(self):
        self._stopping = True
        listener = self._listener
        self._listener = None
        if listener is not None:
            await asyncio.to_thread(listener.close)
        self._subscribers.clear()
        self._states.clear()
        self._loop = None

    def subscribe(self, household_id: str) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=1)
        self._subscribers[household_id].add(queue)
        return queue

    def unsubscribe(self, household_id: str, queue: asyncio.Queue):
        subscribers = self._subscribers.get(household_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(household_id, None)

    def publish(self, household_id: str, state: dict):
        """Publish only the newest state to each device for a household."""
        self._states[household_id] = state
        for queue in tuple(self._subscribers.get(household_id, ())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(state)

    async def _handle_firebase_event(self, event: Any):
        path = str(getattr(event, "path", "/")).strip("/")
        event_type = getattr(event, "event_type", "put")
        data = getattr(event, "data", None)

        if not path:
            await self._handle_root_event(event_type, data)
            return

        household_id, *remaining_path = path.split("/")
        if not household_id:
            return

        if not remaining_path and event_type == "put":
            state = data if isinstance(data, dict) else {}
        else:
            state = await self._read_household_state(household_id)
        self.publish(household_id, state)

    async def _handle_root_event(self, event_type: str, data: Any):
        if not isinstance(data, dict):
            return

        if event_type == "put":
            for household_id, state in data.items():
                if isinstance(state, dict):
                    self._states[household_id] = state
                    if household_id in self._subscribers:
                        self.publish(household_id, state)
            return

        affected_households = {
            str(key).strip("/").split("/", 1)[0]
            for key in data
            if str(key).strip("/")
        }
        for household_id in affected_households:
            state = await self._read_household_state(household_id)
            self.publish(household_id, state)

    async def _read_household_state(self, household_id: str) -> dict:
        state = await asyncio.to_thread(
            realtime_db.reference(f"households/{household_id}").get
        )
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _report_callback_failure(future):
        try:
            future.result()
        except Exception:
            logger.exception("Household Firebase listener callback failed")


household_status_hub = HouseholdStatusHub()
