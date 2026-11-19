"""Persist coalesced transcript snapshots without delaying voice playback."""
import asyncio
from contextlib import suppress

from sqlalchemy import update

from core.database import AsyncSessionLocal
from models.call import CallRecord


class CallTranscriptWriter:
    """Keep at most one pending snapshot and serialize writes for one call."""

    def __init__(self, call_sid: str):
        """Start a per-call persistence worker after its CallRecord has been created."""
        self.call_sid = call_sid
        self._queue = asyncio.Queue(maxsize=1)
        self._closed = False
        self._task = asyncio.create_task(self._run())

    def submit(self, transcript: list, usage: dict):
        """Capture independent copies so later provider events cannot mutate queued data."""
        if self._closed:
            return
        snapshot = ([dict(entry) for entry in transcript], dict(usage))
        if self._queue.full():
            self._queue.get_nowait()
            self._queue.task_done()
        self._queue.put_nowait(snapshot)

    async def _run(self):
        """Save the latest snapshot independently of the browser and provider sockets."""
        while True:
            snapshot = await self._queue.get()
            try:
                if snapshot is None:
                    return
                transcript, usage = snapshot
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(CallRecord).where(CallRecord.call_sid == self.call_sid).values(
                            transcript=transcript,
                            input_tokens=usage.get('input_tokens', 0),
                            output_tokens=usage.get('output_tokens', 0),
                            total_tokens=usage.get('total_tokens', 0),
                            cached_tokens=usage.get('cached_tokens', 0),
                        )
                    )
                    await db.commit()
            except Exception as exc:
                # Do not include transcript contents or provider credentials in diagnostics.
                print(f'[VOICE] Transcript checkpoint failed for {self.call_sid} ({type(exc).__name__}).', flush=True)
            finally:
                self._queue.task_done()

    async def close(self):
        """Flush queued data before finalization; cancel a stalled persistence worker."""
        self._closed = True
        try:
            await asyncio.wait_for(self._queue.join(), timeout=5)
            self._queue.put_nowait(None)
            await self._task
        finally:
            if not self._task.done():
                self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
