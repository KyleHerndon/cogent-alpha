"""coglet CLI — manage a persistent coglet runtime via FastAPI.

Commands:
    coglet runtime start [--port PORT] [--trace PATH]
    coglet runtime stop [--port PORT]
    coglet runtime status [--port PORT]

    coglet create PATH.cog [--port PORT]          -> coglet_id
    coglet stop ID [--port PORT]
    coglet guide ID COMMAND [DATA] [--port PORT]
    coglet observe ID CHANNEL [--follow] [--port PORT]
    coglet connect SRC_ID CHANNEL DEST_ID [--port PORT]

    coglet run PATH.cog [--trace PATH]            (one-shot, no daemon)

MCP endpoint at /mcp.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from coglet.handle import CogBase, Command
from coglet.runtime import CogletRuntime
from coglet.trace import CogletTrace

DEFAULT_PORT = 4510


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest(cog_dir: Path) -> dict[str, Any]:
    manifest_path = cog_dir / "manifest.toml"
    if not manifest_path.exists():
        sys.exit(f"error: {manifest_path} not found")
    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)
    if "coglet" not in manifest or "class" not in manifest["coglet"]:
        sys.exit("error: manifest.toml must have [coglet] with 'class' key")
    return manifest


def resolve_class(dotted: str, cog_dir: Path) -> type:
    parts = dotted.rsplit(".", 1)
    if len(parts) != 2:
        sys.exit(f"error: class must be 'module.ClassName', got '{dotted}'")
    module_name, class_name = parts
    cog_str = str(cog_dir.resolve())
    if cog_str not in sys.path:
        sys.path.insert(0, cog_str)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        sys.exit(f"error: cannot import module '{module_name}': {e}")
    cls = getattr(module, class_name, None)
    if cls is None:
        sys.exit(f"error: class '{class_name}' not found in '{module_name}'")
    return cls


def build_config(manifest: dict[str, Any], cls: type) -> CogBase:
    kwargs = dict(manifest["coglet"].get("kwargs", {}))
    config_section = manifest.get("config", {})
    return CogBase(
        cls=cls,
        kwargs=kwargs,
        restart=config_section.get("restart", "never"),
        max_restarts=config_section.get("max_restarts", 3),
        backoff_s=config_section.get("backoff_s", 1.0),
    )


def load_cogbase(cog_dir: Path) -> CogBase:
    manifest = load_manifest(cog_dir)
    cls = resolve_class(manifest["coglet"]["class"], cog_dir)
    return build_config(manifest, cls)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# FastAPI runtime server
# ---------------------------------------------------------------------------

def create_app(trace_path: str | None = None):
    """Create the FastAPI app with all runtime endpoints + MCP."""
    import signal

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi_mcp import FastApiMCP

    app = FastAPI(title="coglet-runtime", description="Coglet runtime API")

    trace = CogletTrace(trace_path) if trace_path else None
    runtime = CogletRuntime(trace=trace)
    registry: dict[str, tuple[Any, str, str]] = {}  # id -> (handle, cog_dir, class_name)
    connections: list[tuple[str, str, str, asyncio.Task]] = []  # (src_id, ch, dest_id, task)
    next_id = [0]

    def alloc_id() -> str:
        cid = str(next_id[0])
        next_id[0] += 1
        return cid

    def _lookup(coglet_id: str):
        entry = registry.get(coglet_id)
        if not entry:
            raise HTTPException(404, f"no coglet with id '{coglet_id}'")
        return entry

    @app.post("/create", operation_id="create_coglet")
    async def create_coglet(cog_dir: str):
        """Spawn a coglet from a .cog directory. Returns the coglet_id."""
        path = Path(cog_dir)
        if not path.is_dir():
            raise HTTPException(404, f"'{cog_dir}' is not a directory")
        base = load_cogbase(path)
        handle = await runtime.spawn(base)
        cid = alloc_id()
        class_name = type(handle.coglet).__name__
        registry[cid] = (handle, str(path), class_name)
        return {"id": cid, "class": class_name}

    @app.post("/stop/{coglet_id}", operation_id="stop_coglet")
    async def stop_coglet(coglet_id: str):
        """Stop a running coglet by id."""
        handle, _, class_name = _lookup(coglet_id)
        # Cancel any connections involving this coglet
        remaining = []
        for src, ch, dest, task in connections:
            if src == coglet_id or dest == coglet_id:
                task.cancel()
            else:
                remaining.append((src, ch, dest, task))
        connections.clear()
        connections.extend(remaining)
        await runtime._stop_coglet(handle.coglet)
        del registry[coglet_id]
        return {"msg": f"stopped {class_name} (id={coglet_id})"}

    @app.post("/guide/{coglet_id}", operation_id="guide_coglet")
    async def guide_coglet(coglet_id: str, command: str, data: Any = None):
        """Send a command to a coglet's @enact handlers."""
        handle = _lookup(coglet_id)[0]
        await handle.guide(Command(type=command, data=data))
        return {"msg": f"sent '{command}' to {coglet_id}"}

    @app.get("/observe/{coglet_id}/{channel}", operation_id="observe_coglet")
    async def observe_coglet(coglet_id: str, channel: str):
        """Subscribe to a coglet's channel output (SSE stream)."""
        handle = _lookup(coglet_id)[0]
        sub = handle.coglet._bus.subscribe(channel)

        async def event_stream():
            try:
                async for event_data in sub:
                    payload = json.dumps(_serialize(event_data))
                    yield f"data: {payload}\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/connect", operation_id="connect_channel")
    async def connect_channel(src_id: str, channel: str, dest_id: str):
        """Wire src coglet's channel output to dest coglet's @listen handler.

        Every time src transmits on `channel`, the data is dispatched
        to dest's @listen(channel) handler.
        """
        src_handle = _lookup(src_id)[0]
        dest_handle = _lookup(dest_id)[0]
        sub = src_handle.coglet._bus.subscribe(channel)

        async def _pipe():
            try:
                async for data in sub:
                    await dest_handle.coglet._dispatch_listen(channel, data)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_pipe())
        connections.append((src_id, channel, dest_id, task))
        return {
            "msg": f"connected {src_id}:{channel} -> {dest_id}",
            "connections": len(connections),
        }

    @app.delete("/connect", operation_id="disconnect_channel")
    async def disconnect_channel(src_id: str, channel: str, dest_id: str):
        """Remove a channel connection."""
        remaining = []
        found = False
        for src, ch, dest, task in connections:
            if src == src_id and ch == channel and dest == dest_id:
                task.cancel()
                found = True
            else:
                remaining.append((src, ch, dest, task))
        connections.clear()
        connections.extend(remaining)
        if not found:
            raise HTTPException(404, "connection not found")
        return {"msg": f"disconnected {src_id}:{channel} -> {dest_id}"}

    @app.get("/connections", operation_id="list_connections")
    async def list_connections():
        """List all active channel connections."""
        return {
            "connections": [
                {"src": src, "channel": ch, "dest": dest}
                for src, ch, dest, _ in connections
            ]
        }

    @app.get("/status", operation_id="runtime_status")
    async def status():
        """Show runtime status: tree, coglet list, and connections."""
        coglets = []
        for cid, (handle, cog_dir, class_name) in registry.items():
            coglets.append({
                "id": cid,
                "class": class_name,
                "cog_dir": cog_dir,
                "children": len(handle.coglet._children),
            })
        return {
            "tree": runtime.tree(),
            "coglets": coglets,
            "connections": [
                {"src": src, "channel": ch, "dest": dest}
                for src, ch, dest, _ in connections
            ],
        }

    @app.get("/tree", operation_id="runtime_tree")
    async def tree():
        """Return ASCII tree visualization of the coglet hierarchy."""
        return {"tree": runtime.tree()}

    @app.post("/shutdown", operation_id="shutdown_runtime")
    async def shutdown():
        """Shut down the runtime and exit."""
        async def _shutdown():
            await asyncio.sleep(0.5)
            for _, _, _, task in connections:
                task.cancel()
            await runtime.shutdown()
            import os
            os.kill(os.getpid(), signal.SIGTERM)
        asyncio.create_task(_shutdown())
        return {"msg": "shutting down"}

    mcp = FastApiMCP(app, name="coglet-runtime", description="Coglet runtime MCP server")
    mcp.mount_http()

    return app


def start_server(port: int, trace_path: str | None = None) -> None:
    import uvicorn
    app = create_app(trace_path=trace_path)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _post(port: int, path: str, **params) -> dict:
    import urllib.request
    import urllib.parse
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        sys.exit(f"error: {body.get('detail', body)}")


def _delete(port: int, path: str, **params) -> dict:
    import urllib.request
    import urllib.parse
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _get(port: int, path: str) -> dict:
    import urllib.request
    url = f"{_base_url(port)}{path}"
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _observe_sse(port: int, coglet_id: str, channel: str, follow: bool) -> None:
    import urllib.request
    url = f"{_base_url(port)}/observe/{coglet_id}/{channel}"
    try:
        with urllib.request.urlopen(url) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if line.startswith("data: "):
                    print(line[6:])
                    if not follow:
                        return
    except KeyboardInterrupt:
        pass
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


# ---------------------------------------------------------------------------
# One-shot run
# ---------------------------------------------------------------------------

async def run_oneshot(cog_dir: Path, trace_path: str | None = None) -> None:
    import signal as sig
    base = load_cogbase(cog_dir)
    trace = CogletTrace(trace_path) if trace_path else None
    runtime = CogletRuntime(trace=trace)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (sig.SIGINT, sig.SIGTERM):
        loop.add_signal_handler(s, stop.set)

    await runtime.run(base)
    print(runtime.tree())
    await stop.wait()
    print("\nshutting down...")
    await runtime.shutdown()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    port_args = argparse.ArgumentParser(add_help=False)
    port_args.add_argument("--port", type=int, default=DEFAULT_PORT,
                           help=f"runtime API port (default: {DEFAULT_PORT})")

    parser = argparse.ArgumentParser(prog="coglet", description="Manage coglet runtimes.")
    sub = parser.add_subparsers(dest="command")

    # runtime
    rt = sub.add_parser("runtime", help="manage the runtime daemon")
    rt_sub = rt.add_subparsers(dest="action")
    rt_start = rt_sub.add_parser("start", parents=[port_args])
    rt_start.add_argument("--trace", type=str, default=None)
    rt_sub.add_parser("stop", parents=[port_args])
    rt_sub.add_parser("status", parents=[port_args])

    # create
    cr = sub.add_parser("create", parents=[port_args])
    cr.add_argument("cog_dir", type=Path)

    # stop
    st = sub.add_parser("stop", parents=[port_args])
    st.add_argument("id", type=str)

    # observe
    ob = sub.add_parser("observe", parents=[port_args])
    ob.add_argument("id", type=str)
    ob.add_argument("channel", type=str)
    ob.add_argument("--follow", action="store_true")

    # guide
    gu = sub.add_parser("guide", parents=[port_args])
    gu.add_argument("id", type=str)
    gu.add_argument("cmd_type", metavar="command", type=str)
    gu.add_argument("data", nargs="?", default=None)

    # connect
    cn = sub.add_parser("connect", parents=[port_args],
                        help="wire src channel -> dest @listen")
    cn.add_argument("src_id", type=str, help="source coglet id")
    cn.add_argument("channel", type=str, help="channel name")
    cn.add_argument("dest_id", type=str, help="destination coglet id")

    # disconnect
    dc = sub.add_parser("disconnect", parents=[port_args])
    dc.add_argument("src_id", type=str)
    dc.add_argument("channel", type=str)
    dc.add_argument("dest_id", type=str)

    # connections
    sub.add_parser("connections", parents=[port_args], help="list active connections")

    # run (one-shot)
    rn = sub.add_parser("run")
    rn.add_argument("cog_dir", type=Path)
    rn.add_argument("--trace", type=str, default=None)

    args = parser.parse_args()
    port = getattr(args, "port", DEFAULT_PORT)

    if args.command == "runtime":
        if args.action == "start":
            start_server(port, trace_path=args.trace)
        elif args.action == "stop":
            print(_post(port, "/shutdown").get("msg"))
        elif args.action == "status":
            resp = _get(port, "/status")
            print(resp["tree"])
            if resp["coglets"]:
                print()
                for c in resp["coglets"]:
                    print(f"  id={c['id']}  class={c['class']}  children={c['children']}  cog_dir={c['cog_dir']}")
            if resp.get("connections"):
                print()
                for c in resp["connections"]:
                    print(f"  {c['src']}:{c['channel']} -> {c['dest']}")
            if not resp["coglets"]:
                print("\nno coglets running.")

    elif args.command == "create":
        if not args.cog_dir.is_dir():
            sys.exit(f"error: '{args.cog_dir}' is not a directory")
        resp = _post(port, "/create", cog_dir=str(args.cog_dir.resolve()))
        print(resp["id"])

    elif args.command == "stop":
        print(_post(port, f"/stop/{args.id}").get("msg"))

    elif args.command == "observe":
        _observe_sse(port, args.id, args.channel, args.follow)

    elif args.command == "guide":
        data_val = None
        if args.data:
            try:
                data_val = json.loads(args.data)
            except json.JSONDecodeError:
                data_val = args.data
        params = {"command": args.cmd_type}
        if data_val is not None:
            params["data"] = json.dumps(data_val) if not isinstance(data_val, str) else data_val
        print(_post(port, f"/guide/{args.id}", **params).get("msg"))

    elif args.command == "connect":
        resp = _post(port, "/connect",
                     src_id=args.src_id, channel=args.channel, dest_id=args.dest_id)
        print(resp.get("msg"))

    elif args.command == "disconnect":
        resp = _delete(port, "/connect",
                       src_id=args.src_id, channel=args.channel, dest_id=args.dest_id)
        print(resp.get("msg"))

    elif args.command == "connections":
        resp = _get(port, "/connections")
        for c in resp["connections"]:
            print(f"  {c['src']}:{c['channel']} -> {c['dest']}")
        if not resp["connections"]:
            print("no connections.")

    elif args.command == "run":
        if not args.cog_dir.is_dir():
            sys.exit(f"error: '{args.cog_dir}' is not a directory")
        asyncio.run(run_oneshot(args.cog_dir, trace_path=args.trace))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
