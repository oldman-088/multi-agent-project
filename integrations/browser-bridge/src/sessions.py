"""Session registry: device connections, browser tabs, per-tab queues and request routing.

Rules enforced here:
- One in-flight request per tab (the per-tab lock). Extra requests queue behind it.
- A request is dispatched only while its tab reports READY. WAITING_FOR_USER blocks
  dispatch; cancel stays allowed.
- Idempotency keys are remembered per tab. A repeated key returns the original request.
- If a connection drops while a request was dispatched, the request fails with
  UNCERTAIN_SUBMISSION. It is never resubmitted automatically.
- Prompts and responses are never logged; only ids, lengths and states are.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from protocol import (
    MAX_RESULT_CHARS,
    CloseCode,
    ErrorCode,
    RequestStatus,
    SessionState,
)

log = logging.getLogger("browser_bridge.sessions")
_ERROR_VALUES = frozenset(e.value for e in ErrorCode)

SendFn = Callable[[dict[str, object]], Awaitable[None]]
CloseFn = Callable[[int], Awaitable[None]]


class TabNotFound(LookupError):
    pass


class RequestNotFound(LookupError):
    pass


@dataclass
class Connection:
    device_id: str
    script_version: tuple[int, ...]
    send_fn: SendFn
    close_fn: CloseFn
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message: dict[str, object]) -> None:
        async with self._lock:
            await self.send_fn(message)

    async def close(self, code: CloseCode) -> None:
        try:
            await self.close_fn(int(code))
        except Exception:  # noqa: BLE001 - the socket may already be closed; any transport error is fine
            log.debug("ws.close_failed code=%d", int(code))


@dataclass
class Tab:
    tab_id: str
    device_id: str
    client_tab_id: str
    state: SessionState = SessionState.DISCONNECTED
    agent_state: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    pending: int = 0
    by_key: dict[str, str] = field(default_factory=dict)


@dataclass
class TabRequest:
    request_id: str
    tab_id: str
    prompt: str
    idempotency_key: str
    timeout_s: float
    queue_position: int
    status: RequestStatus = RequestStatus.QUEUED
    text: str = ""
    error_code: str | None = None
    dispatched: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class TabView:
    tab_id: str
    device_id: str
    state: SessionState
    agent_state: str | None
    pending: int


class SessionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._tabs: dict[str, Tab] = {}
        self._tab_index: dict[tuple[str, str], str] = {}
        self._requests: dict[str, TabRequest] = {}
        self._runners: set[asyncio.Task[None]] = set()

    # ----- connections -------------------------------------------------------

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connections

    async def attach(self, conn: Connection) -> None:
        old = self._connections.pop(conn.device_id, None)
        if old is not None:
            await self._on_disconnect(conn.device_id)
            await old.close(CloseCode.REPLACED)
        self._connections[conn.device_id] = conn
        log.info(
            "device.attached device=%s version_len=%d",
            conn.device_id,
            len(conn.script_version),
        )

    async def detach(self, conn: Connection) -> None:
        if self._connections.get(conn.device_id) is not conn:
            return  # already replaced or revoked
        del self._connections[conn.device_id]
        await self._on_disconnect(conn.device_id)
        log.info("device.detached device=%s", conn.device_id)

    async def revoke_device(self, device_id: str) -> None:
        conn = self._connections.pop(device_id, None)
        for tab in self._tabs_of(device_id):
            for req in self._open_requests(tab):
                self._finish(
                    req,
                    RequestStatus.FAILED,
                    ErrorCode.UNCERTAIN_SUBMISSION
                    if req.dispatched
                    else ErrorCode.DEVICE_OFFLINE,
                )
            await self._set_state(tab, SessionState.DISCONNECTED)
        if conn is not None:
            await conn.close(CloseCode.REVOKED)

    async def _on_disconnect(self, device_id: str) -> None:
        for tab in self._tabs_of(device_id):
            for req in self._open_requests(tab):
                if req.dispatched:
                    self._finish(
                        req, RequestStatus.FAILED, ErrorCode.UNCERTAIN_SUBMISSION
                    )
            await self._set_state(tab, SessionState.DISCONNECTED)

    # ----- tabs --------------------------------------------------------------

    async def update_tab(
        self,
        device_id: str,
        client_tab_id: str,
        state: SessionState,
        agent_state: str | None,
    ) -> TabView:
        key = (device_id, client_tab_id)
        tab_id = self._tab_index.get(key)
        if tab_id is None:
            tab_id = "tab_" + secrets.token_hex(6)
            self._tab_index[key] = tab_id
            self._tabs[tab_id] = Tab(
                tab_id=tab_id, device_id=device_id, client_tab_id=client_tab_id
            )
        tab = self._tabs[tab_id]
        tab.agent_state = agent_state
        await self._set_state(tab, state)
        return self._view(tab)

    def list_tabs(self) -> list[TabView]:
        return [self._view(t) for t in self._tabs.values()]

    def _view(self, tab: Tab) -> TabView:
        return TabView(
            tab.tab_id, tab.device_id, tab.state, tab.agent_state, tab.pending
        )

    def _tabs_of(self, device_id: str) -> list[Tab]:
        return [t for t in self._tabs.values() if t.device_id == device_id]

    def _open_requests(self, tab: Tab) -> list[TabRequest]:
        return [
            r
            for r in self._requests.values()
            if r.tab_id == tab.tab_id and not r.done.is_set()
        ]

    async def _set_state(self, tab: Tab, state: SessionState) -> None:
        async with tab.cond:
            tab.state = state
            tab.cond.notify_all()

    # ----- requests ----------------------------------------------------------

    def enqueue(
        self, tab_id: str, prompt: str, idempotency_key: str, timeout_s: float
    ) -> TabRequest:
        """Register a request and start its runner. Returns immediately."""
        tab = self._tabs.get(tab_id)
        if tab is None:
            raise TabNotFound(tab_id)
        existing_id = tab.by_key.get(idempotency_key)
        if existing_id is not None:
            return self._requests[existing_id]

        req = TabRequest(
            request_id="req_" + secrets.token_hex(8),
            tab_id=tab_id,
            prompt=prompt,
            idempotency_key=idempotency_key,
            timeout_s=timeout_s,
            queue_position=tab.pending,
        )
        tab.by_key[idempotency_key] = req.request_id
        self._requests[req.request_id] = req
        tab.pending += 1
        log.info(
            "request.queued request=%s position=%d chars=%d",
            req.request_id,
            req.queue_position,
            len(prompt),
        )
        task = asyncio.ensure_future(self._run(tab, req))
        self._runners.add(task)
        task.add_done_callback(self._runners.discard)
        return req

    async def _run(self, tab: Tab, req: TabRequest) -> None:
        exec_task = asyncio.ensure_future(self._execute(tab, req))
        done_task = asyncio.ensure_future(req.done.wait())
        try:
            await asyncio.wait(
                {exec_task, done_task},
                timeout=req.timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not req.done.is_set():
                if req.dispatched:
                    await self._send_cancel(tab, req)
                    self._finish(
                        req, RequestStatus.FAILED, ErrorCode.GENERATION_TIMEOUT
                    )
                else:
                    self._finish(req, RequestStatus.FAILED, ErrorCode.TIMEOUT)
        finally:
            exec_task.cancel()
            done_task.cancel()
            tab.pending -= 1

    async def _execute(self, tab: Tab, req: TabRequest) -> None:
        async with tab.lock:
            if req.done.is_set():
                return
            async with tab.cond:
                await tab.cond.wait_for(
                    lambda: tab.state is SessionState.READY or req.done.is_set()
                )
            if req.done.is_set():
                return
            conn = self._connections.get(tab.device_id)
            if conn is None:
                self._finish(req, RequestStatus.FAILED, ErrorCode.DEVICE_OFFLINE)
                return
            req.status = RequestStatus.DISPATCHED
            req.dispatched = True
            try:
                await conn.send(
                    {
                        "type": "request",
                        "request_id": req.request_id,
                        "tab_id": tab.client_tab_id,
                        "prompt": req.prompt,
                        "idempotency_key": req.idempotency_key,
                        "timeout_ms": int(req.timeout_s * 1000),
                    }
                )
            except Exception:  # noqa: BLE001 - a dead socket must fail the request, not the runner
                log.warning("request.send_failed request=%s", req.request_id)
                self._finish(req, RequestStatus.FAILED, ErrorCode.SEND_FAILED)
                return
            log.info("request.dispatched request=%s", req.request_id)
            await req.done.wait()

    async def cancel(self, tab_id: str, request_id: str) -> TabRequest:
        req = self._requests.get(request_id)
        if req is None or req.tab_id != tab_id:
            raise RequestNotFound(request_id)
        if req.done.is_set():
            return req
        if req.dispatched:
            await self._send_cancel(self._tabs[tab_id], req)
        self._finish(req, RequestStatus.CANCELLED, ErrorCode.CANCELLED)
        return req

    async def _send_cancel(self, tab: Tab, req: TabRequest) -> None:
        conn = self._connections.get(tab.device_id)
        if conn is None:
            return
        try:
            await conn.send({"type": "cancel", "request_id": req.request_id})
        except Exception:  # noqa: BLE001 - a dead socket must not break cancellation
            log.warning("request.cancel_send_failed request=%s", req.request_id)

    def _owned(self, device_id: str, request_id: str) -> TabRequest | None:
        req = self._requests.get(request_id)
        if req is None or req.done.is_set() or not req.dispatched:
            return None
        if self._tabs[req.tab_id].device_id != device_id:
            return None
        return req

    def handle_delta(self, device_id: str, request_id: str, text: str) -> None:
        req = self._owned(device_id, request_id)
        if req is None:
            return
        req.text = (req.text + text)[:MAX_RESULT_CHARS]

    async def handle_result(
        self,
        device_id: str,
        request_id: str,
        status: str,
        text: str | None,
        error_code: str | None,
    ) -> None:
        req = self._owned(device_id, request_id)
        if req is None:
            return
        if status == "completed":
            if text is not None:
                req.text = text[:MAX_RESULT_CHARS]
            self._finish(req, RequestStatus.COMPLETED, None)
        else:
            code = (
                error_code
                if error_code in _ERROR_VALUES
                else ErrorCode.PROVIDER_ERROR.value
            )
            self._finish(req, RequestStatus.FAILED, code)
        tab = self._tabs[req.tab_id]
        if tab.state is SessionState.BUSY:
            await self._set_state(tab, SessionState.READY)

    def _finish(
        self, req: TabRequest, status: RequestStatus, error_code: str | None
    ) -> None:
        if req.done.is_set():
            return
        req.status = status
        req.error_code = str(error_code) if error_code is not None else None
        req.prompt = ""
        req.done.set()
        log.info(
            "request.finished request=%s status=%s chars=%d",
            req.request_id,
            status.value,
            len(req.text),
        )

    def get_request(self, tab_id: str, request_id: str) -> TabRequest:
        req = self._requests.get(request_id)
        if req is None or req.tab_id != tab_id:
            raise RequestNotFound(request_id)
        return req
