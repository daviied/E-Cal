"""Syncing with an HP Prime G2 from the web page.

The calculator's USB cable is plugged into the computer the *browser* runs on,
so the browser (WebHID, see frontend/hp.js) does all the talking to the
calculator. The merge logic is the HP Prime sync tool's own (hpprime2/sync/
cvsync, CalcVault 2's, which also copies the shared lines), run here on the
server: it needs to read and write the calculator's
notes, and does so by asking the browser over a WebSocket, one request at a
time. The page never sees the merge, only a log and the occasional
"are you sure" question.

    browser                                   server
       | -- {type: sync} ------------------->  starts cvsync.webrun.sync_once
       | <-- {type: req, op: read, name} ----  (needs a note)
       | -- {type: reply, id, text} -------->
       | <-- {type: say, text} --------------  progress for the log
       | <-- {type: confirm, text} ---------   deletions / conflicts
       | -- {type: confirm, id, yes} ------->
       | <-- {type: done, ...} -------------
"""
import asyncio
import os
import queue
import sys
import threading

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from . import db

HP_SYNC_DIR = os.path.abspath(
    os.environ.get("HP_SYNC_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "hpprime2", "sync"))
)
STATE_DIR = os.environ.get(
    "HP_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "hpsync")
)

try:
    if HP_SYNC_DIR not in sys.path:
        sys.path.insert(0, HP_SYNC_DIR)
    from cvsync import webrun  # noqa: E402

    UNAVAILABLE = None
except Exception as e:  # noqa: BLE001 - the rest of the app must run without it
    webrun = None
    UNAVAILABLE = "the HP Prime sync code was not found (%s)" % e

router = APIRouter()


class RemoteError(Exception):
    pass


class DbApi:
    """The web app's data, in the shape cvsync.api.Api has, without HTTP."""

    def tree(self):
        return db.get_tree()

    def get_calc(self, cid):
        calc = db.get_calculator(int(cid))
        if calc is None:
            raise RemoteError("calculator %s no longer exists" % cid)
        return calc

    def create_folder(self, name, parent_id):
        return db.create_folder(name, parent_id)

    def update_folder(self, fid, name, parent_id):
        return db.update_folder(int(fid), name, parent_id, True)

    def delete_folder(self, fid):
        return {"ok": db.delete_folder(int(fid))}

    def create_calc(self, name, folder_id):
        return db.create_calculator(name, folder_id, "calculator")

    def update_calc(self, cid, name, folder_id, data):
        res = db.update_calculator(int(cid), name, folder_id, True, data)
        if res is None:
            raise RemoteError("calculator %s no longer exists" % cid)
        return res

    def delete_calc(self, cid):
        return {"ok": db.delete_calculator(int(cid))}


_CLOSED = object()


class Bridge:
    """Blocking requests to the browser, made from the sync's worker thread."""

    def __init__(self, loop, ws):
        self.loop, self.ws = loop, ws
        self.replies = queue.Queue()
        self.n = 0

    def send(self, msg):
        asyncio.run_coroutine_threadsafe(self.ws.send_json(msg), self.loop).result(timeout=30)

    def ask(self, msg, timeout):
        self.n += 1
        mid = self.n
        self.send(dict(msg, id=mid))
        while True:
            try:
                r = self.replies.get(timeout=timeout)
            except queue.Empty:
                raise RemoteError("the browser stopped answering")
            if r is _CLOSED:
                raise RemoteError("the browser disconnected")
            if r.get("id") == mid:
                return r


class RemoteTarget:
    """The calculator, as store.UsbTarget would be, but reached through the
    browser. The browser does the USB retries itself; an error it reports
    comes out here as an exception that ends the sync."""

    label = "calculator"
    READ_TIMEOUT = 180  # a note can take a minute to arrive

    def __init__(self, bridge):
        self.bridge = bridge
        self.names = None  # notes in the browser's last complete backup

    def prefetch(self):
        """Everything at once at the start of a sync (store.read_vault): the
        browser takes one backup and serves the reads that follow from it,
        as store.UsbTarget does. See cvsync.primelink for why."""
        r = self.bridge.ask({"type": "req", "op": "prefetch"}, 600)
        if r.get("error"):
            raise RemoteError(r["error"])
        self.names = set(r.get("names") or []) if r.get("complete") else None

    def present(self, name):
        return None if self.names is None else name in self.names

    def read(self, name="CVDATA", fresh=False):
        r = self.bridge.ask({"type": "req", "op": "read", "name": name, "fresh": fresh}, self.READ_TIMEOUT)
        if r.get("error"):
            raise RemoteError(r["error"])
        return r.get("text")

    def write(self, text, name="CVDATA", new=False):
        r = self.bridge.ask({"type": "req", "op": "write", "name": name, "text": text, "new": bool(new)},
                            self.READ_TIMEOUT)
        if r.get("error"):
            raise RemoteError(r["error"])
        self.names = None  # the browser's backup is out of date now

    def read_rev(self):
        # Always asked for by name: this is how a change on the calculator is noticed.
        return self.read("CVREV", fresh=True)

    def write_rev(self, token):
        self.write(token, "CVREV")

    def close(self):
        pass


_lock = threading.Lock()


def _run_sync(bridge, auto):
    if not _lock.acquire(blocking=False):
        return {"type": "done", "code": 1, "changed": False, "busy": True,
                "summary": "", "error": "another sync is already running"}
    try:
        def say(text):
            bridge.send({"type": "say", "text": text})

        def confirm(text):
            return bool(bridge.ask({"type": "confirm", "text": text}, 600).get("yes"))

        os.makedirs(STATE_DIR, exist_ok=True)
        res = webrun.sync_once(DbApi(), RemoteTarget(bridge), STATE_DIR, say, confirm, auto)
        return dict(res, type="done")
    except RemoteError as e:
        return {"type": "done", "code": 1, "changed": False, "summary": "", "error": str(e)}
    except Exception as e:  # noqa: BLE001 - tell the page rather than drop the socket
        return {"type": "done", "code": 1, "changed": False, "summary": "",
                "error": "%s: %s" % (type(e).__name__, e)}
    finally:
        _lock.release()


async def _sync_task(ws, bridge, auto):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _run_sync, bridge, auto)
    try:
        await ws.send_json(result)
    except Exception:  # noqa: BLE001 - the page went away
        pass


@router.get("/api/hp/status")
def hp_status(request: Request):
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"available": webrun is not None, "reason": UNAVAILABLE}


@router.websocket("/api/hp/ws")
async def hp_ws(ws: WebSocket):
    # Same session cookie as the rest of the API; refuse anyone not logged in.
    if not ws.session.get("authed"):
        await ws.close(code=4401)
        return
    await ws.accept()
    if webrun is None:
        await ws.send_json({"type": "done", "code": 1, "changed": False, "summary": "", "error": UNAVAILABLE})
        await ws.close()
        return
    bridge = Bridge(asyncio.get_running_loop(), ws)
    task = None
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "sync":
                if task is None or task.done():
                    task = asyncio.create_task(_sync_task(ws, bridge, bool(msg.get("auto"))))
            elif kind in ("reply", "confirm"):
                bridge.replies.put(msg)
    except WebSocketDisconnect:
        pass
    finally:
        bridge.replies.put(_CLOSED)
