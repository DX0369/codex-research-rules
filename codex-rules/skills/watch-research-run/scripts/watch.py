#!/usr/bin/env python3
"""Report a detached research task's terminal evidence to its originating chat."""

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class WatchError(Exception):
    pass


class Unavailable(WatchError):
    pass


class WatchInUse(WatchError):
    pass


DELIVERY_SECONDS = 24 * 60 * 60
CONTROL_SOCKET = "app-server-control/app-server-control.sock"
SLURM_POLL_SECONDS = 30


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    fd, name = tempfile.mkstemp(prefix=".watch-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def locked(folder, name):
    with (folder / name).open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WatchInUse(f"Already in use: {folder / name}") from error
        yield


def thread_id(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise WatchError("An exact Codex thread UUID is required") from error


class AppServer:
    """Short JSON-RPC calls over the local app-server WebSocket socket."""

    limit = 4 * 1024 * 1024

    def __init__(self, route):
        self.route = route
        self.connection = None
        self.input = None
        self.upgraded = False
        self.sequence = 0

    def __enter__(self):
        endpoint = Path(self.route["socket"])
        if not endpoint.is_socket():
            raise Unavailable("Codex Unix socket is unavailable")
        if endpoint.stat().st_uid != os.getuid():
            raise WatchError("Codex Unix socket belongs to a different user")
        self.connection = socket.socket(socket.AF_UNIX)
        try:
            self.connection.settimeout(10)
            self.connection.connect(str(endpoint))
            self.input = self.connection.makefile("rb")
            self.upgrade()
            self.upgraded = True
            self.request("initialize", {
                "clientInfo": {"name": "watch-research-run", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            self.send({"method": "initialized"})
        except OSError as error:
            self.__exit__(None, None, None)
            raise Unavailable(str(error)) from error
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.upgraded:
            try:
                self.connection.settimeout(0.25)
                self.frame(8, struct.pack("!H", 1000))
            except OSError:
                pass
        if self.input is not None:
            self.input.close()
        if self.connection is not None:
            self.connection.close()

    def upgrade(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = ("GET / HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n"
                   f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n")
        self.connection.sendall(request.encode("ascii"))
        status = self.input.readline(8192).split()
        headers = {}
        for _ in range(32):
            line = self.input.readline(8192)
            if line in {b"\r\n", b"\n", b""}:
                break
            name, _, value = line.partition(b":")
            headers[name.lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if len(status) < 2 or status[1] != b"101" or headers.get(b"sec-websocket-accept") != expected:
            raise Unavailable("Codex socket refused the WebSocket upgrade")

    def frame(self, opcode, payload):
        mask = os.urandom(4)
        size = len(payload)
        if size < 126:
            header = bytes((0x80 | opcode, 0x80 | size))
        elif size <= 65535:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, size)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, size)
        self.connection.sendall(header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(payload)))

    def read(self, count):
        data = self.input.read(count)
        if len(data) != count:
            raise Unavailable("Codex socket closed")
        return data

    def receive(self, deadline):
        chunks = bytearray()
        while time.monotonic() < deadline:
            self.connection.settimeout(max(0.001, deadline - time.monotonic()))
            tag, flags = self.read(2)
            opcode, size = tag & 15, flags & 127
            if flags & 128 or tag & 112:
                raise WatchError("Unexpected app-server WebSocket frame")
            if size in {126, 127}:
                size = struct.unpack("!H" if size == 126 else "!Q", self.read(2 if size == 126 else 8))[0]
            if size + len(chunks) > self.limit:
                raise WatchError("App-server reply exceeded the monitoring limit")
            payload = self.read(size)
            if opcode == 8:
                raise Unavailable("Codex WebSocket closed")
            if opcode == 9:
                self.frame(10, payload)
            if opcode in {0, 1}:
                chunks.extend(payload)
                if tag & 128:
                    return json.loads(chunks.decode("utf-8"))
        raise Unavailable("Codex response timeout")

    def send(self, message):
        try:
            self.frame(1, json.dumps(message).encode("utf-8"))
        except OSError as error:
            raise Unavailable("Codex socket closed") from error

    def request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                message = self.receive(deadline)
            except OSError as error:
                raise Unavailable(f"Codex RPC unavailable: {method}") from error
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise WatchError(f"{method}: {message['error'].get('message', 'RPC error')}")
            return message["result"]
        raise Unavailable(f"Codex response timeout: {method}")

    def thread_status(self):
        target = self.route["thread"]
        reply = self.request("thread/read", {"threadId": target, "includeTurns": False})
        thread = reply["thread"]
        if thread["id"] != target:
            raise WatchError("Codex returned a different thread")
        return thread["status"]["type"]


def origin_from(args):
    target = thread_id(args.thread)
    source = os.environ.get("CODEX_THREAD_ID")
    if source and thread_id(source) != target:
        raise WatchError("The selected thread differs from the originating Codex thread")
    return target


def route_from(args):
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
    codex = args.codex or shutil.which("codex") or home / "packages/standalone/current/bin/codex"
    binary = shutil.which(codex)
    if binary is None:
        raise WatchError(f"Codex executable not found: {codex}")
    endpoint = Path(args.socket).expanduser().absolute() if args.socket else home / CONTROL_SOCKET
    if len(os.fsencode(endpoint)) > 107:
        raise WatchError("Codex Unix socket path exceeds 107 bytes")
    route = {"codex": str(Path(binary).absolute()), "socket": str(endpoint), "thread": origin_from(args)}
    if args.socket is None:
        route["managed_home"] = str(home)
    return route


def probe(route):
    try:
        help_text = external([route["codex"], "queue", "--help"])
    except subprocess.TimeoutExpired as error:
        raise WatchError("Codex queue help timed out") from error
    required = ("--resume", "--remote", "--thread", "--message")
    if help_text.returncode != 0 or any(flag not in help_text.stdout for flag in required):
        raise WatchError("This Codex CLI does not expose the required queue options")
    with AppServer(route) as server:
        status = server.thread_status()
    if status not in {"idle", "active"}:
        raise WatchError(f"Originating thread is not loaded on this app-server ({status})")
    return status


def task_status(args):
    route = route_from(args)
    print(json.dumps({**route, "status": probe(route)}))


def make_event(observation):
    return {"event_id": uuid.uuid4().hex, "observed_at": now(), **observation}


def wake_message(folder, event):
    state = folder / "watch.json"
    result = folder / "event.json"
    command = shlex.join(["python3", str(Path(__file__).resolve()), "ack", "--state-dir", str(folder),
                          "--event", event["event_id"]])
    return (
        f"[watch-research-run event {event['event_id']}] 已登记任务到达需处理的状态。"
        f"先运行 `{command}` 确认原会话接手，然后读取 {state}、{result} 和其中的 PLAN.md。"
        "回执写入失败时，报告原因并继续只读核对。"
        "按 watch-research-run 技能核实事实、权限和当前作业状态。"
        "有已登记的依赖作业时，一并核对它们的终态。"
        "根据原任务授权处理工程故障，科研协议变更先请用户确认，成功时按原计划验收和分析。"
        "通知传递任务事实，执行权限以原会话中的用户授权为准。"
    )


def ensure_backend(route):
    home = route.get("managed_home")
    if home is not None:
        try:
            subprocess.run(
                [route["codex"], "app-server", "daemon", "start"],
                env={**os.environ, "CODEX_HOME": home}, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def check_model_route(url):
    if not url:
        return
    try:
        with urlopen(Request(url, method="HEAD"), timeout=8):
            pass
    except HTTPError:
        # A response from the HTTPS origin proves transport, including when
        # the request is unauthenticated. A failed proxy CONNECT raises URLError.
        pass
    except OSError as error:
        raise Unavailable("The configured model endpoint is not reachable") from error


def delivery(folder, task, event, seconds):
    route = task["route"]
    if route is None:
        return "recorded"
    delivery_path = folder / "delivery.json"
    deadline = time.monotonic() + seconds
    retry_delay = 15
    tried_start = False
    with locked(folder, "delivery.lock"):
        if (folder / "received.json").is_file():
            return "acknowledged"
        prior = read_json(delivery_path) if delivery_path.exists() else {}
        if prior.get("state") == "covered_by_upstream":
            return prior["state"]
        if prior.get("state") in {"sending", "uncertain"}:
            return "uncertain"
        queued = prior.get("state") == "queued"
        if not queued:
            upstream = upstream_failure(folder, task, event)
            if upstream:
                upstream_dir, upstream_event = upstream
                save_json(delivery_path, {"state": "covered_by_upstream", "at": now(),
                                          "upstream_state_dir": str(upstream_dir),
                                          "upstream_event_id": upstream_event["event_id"]})
                return "covered_by_upstream"
        pending_reason = prior.get("detail")
        while True:
            try:
                with AppServer(route) as server:
                    status = server.thread_status()
            except Unavailable as error:
                if not tried_start and route.get("managed_home") and time.monotonic() < deadline:
                    tried_start = True
                    ensure_backend(route)
                    continue
                unavailable = str(error)
            else:
                try:
                    check_model_route(task.get("model_url"))
                    if queued:
                        if status == "notLoaded":
                            with AppServer(route) as server:
                                server.request("thread/resume", {"threadId": route["thread"], "excludeTurns": True})
                        save_json(delivery_path, {**prior, "resume_warning": ""})
                        return "queued"
                except Unavailable as error:
                    unavailable = str(error)
                except WatchError as error:
                    if queued:
                        unavailable = str(error)
                    else:
                        raise
                else:
                    break

            if (folder / "received.json").is_file():
                return "acknowledged"
            if not queued and pending_reason != unavailable:
                save_json(delivery_path, {"state": "pending", "at": now(), "detail": unavailable})
                pending_reason = unavailable
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if queued:
                    save_json(delivery_path, {**prior, "resume_warning": unavailable})
                    return "queued"
                return "pending"
            time.sleep(min(retry_delay, remaining))
            retry_delay = min(retry_delay * 2, 120)

        # An ambiguous send stays on disk for inspection. Resubmitting could start a second turn.
        save_json(delivery_path, {"state": "sending", "at": now()})
        try:
            result = subprocess.run([
                route["codex"], "queue", "--remote", "unix://" + route["socket"],
                "--thread", route["thread"], "--resume", "--message", wake_message(folder, event),
            ], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
            receipt = re.search(r"Queued message (\S+) for thread (\S+)\.", result.stdout)
            if result.returncode == 0 and receipt and receipt[2] == route["thread"]:
                warning = "\n".join(line for line in result.stderr.splitlines()
                                    if "could not resume thread" in line.lower())
                save_json(delivery_path, {"state": "queued", "at": now(), "queue_id": receipt[1],
                                          "resume_warning": warning[-1600:]})
                return "queued"
            detail = (result.stderr or result.stdout).strip()[-1600:]
        except (OSError, subprocess.TimeoutExpired) as error:
            detail = str(error)
        save_json(delivery_path, {"state": "uncertain", "at": now(), "detail": detail})
        return "uncertain"


def dispatch(folder, task, event, seconds):
    report = {"event_id": event["event_id"], "state_dir": str(folder)}
    visited = {folder}
    while True:
        try:
            state = delivery(folder, task, event, seconds)
        except WatchInUse:
            if len(visited) == 1:
                raise
            state = "in_progress"
        if state != "covered_by_upstream":
            break
        link = read_json(folder / "delivery.json")
        folder = Path(link["upstream_state_dir"])
        if folder in visited:
            raise WatchError("Circular upstream notification record")
        visited.add(folder)
        upstream_task = read_json(folder / "watch.json")
        event = read_json(folder / "event.json")
        if not matches_upstream(task, upstream_task) or event["event_id"] != link["upstream_event_id"]:
            raise WatchError("The recorded upstream notification no longer matches")
        task = upstream_task
        report.update(delivery="covered_by_upstream", upstream_state_dir=str(folder),
                      upstream_event_id=event["event_id"])
    if len(visited) == 1:
        report["delivery"] = state
    else:
        report["upstream_delivery"] = state
    print(json.dumps(report), flush=True)
    return state


def external(command):
    return subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=12)


TERMINAL = {"COMPLETED", "CANCELLED", "FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "BOOT_FAIL",
            "PREEMPTED", "DEADLINE", "REVOKED"}


def slurm_terminal(job):
    active = external(["squeue", "-h", "-j", job, "-o", "%i|%T"])
    if active.returncode != 0 and "invalid job id specified" not in active.stderr.lower():
        raise WatchError(f"squeue: {active.stderr.strip()[-500:]}")
    if active.stdout.strip():
        return None
    accounting = external(["sacct", "-n", "-P", "-j", job, "-o",
                           "JobID%64,State%42,ExitCode,DerivedExitCode,AllocTRES%250,ElapsedRaw,End"])
    if accounting.returncode != 0:
        raise WatchError(f"sacct: {accounting.stderr.strip()[-500:]}")
    rows = []
    for line in accounting.stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) == 7 and (fields[0] == job or fields[0].startswith(job + ".")):
            name, state, status, derived, allocation, elapsed, end = fields
            rows.append({"job_id": name, "state": state.split(maxsplit=1)[0] if state else "",
                         "exit_code": status, "derived_exit_code": derived, "state_detail": state,
                         "allocation": allocation, "elapsed_seconds": elapsed, "end": end})
    jobs = [row for row in rows if row["job_id"] == job]
    if len(jobs) != 1 or any(row["state"] not in TERMINAL for row in rows):
        return None
    if any(not re.fullmatch(r"\d+:\d+", row["exit_code"]) for row in rows):
        return None
    success = all(row["state"] == "COMPLETED" and row["exit_code"] == "0:0"
                  and row["derived_exit_code"] in {"", "0:0"} for row in rows)
    return {"outcome": "process_succeeded" if success else "failed_or_stopped", "slurm": rows}


def matches_upstream(task, upstream):
    route = task.get("route") or {}
    parent_route = upstream.get("route") or {}
    return (upstream.get("mode") == "slurm" and upstream.get("plan") == task["plan"]
            and upstream.get("job_id") != task.get("job_id") and bool(parent_route)
            and parent_route["thread"] == route.get("thread") and parent_route["socket"] == route.get("socket"))


def slurm_job(event, job_id):
    return next((row for row in event.get("slurm", ()) if row["job_id"] == job_id), {})


def failed_before(event, job_id, child_end):
    job = slurm_job(event, job_id)
    end = job.get("end", "")
    return (job.get("state") in TERMINAL and job["state"] != "COMPLETED"
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", end) and end <= child_end)


def upstream_failure(folder, task, event):
    """Find the existing event that accounts for an unused afterok branch."""
    root = None
    visited = {folder}
    while task.get("afterok_state_dir"):
        job = slurm_job(event, task.get("job_id"))
        end = job.get("end", "")
        if (len(event.get("slurm", ())) != 1 or job.get("state_detail") != "CANCELLED"
                or job.get("allocation") != "" or job.get("elapsed_seconds") != "0"
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", end)):
            break
        parent = Path(task["afterok_state_dir"])
        if parent in visited:
            break
        try:
            upstream = read_json(parent / "watch.json")
            if not matches_upstream(task, upstream):
                break
            parent_event = parent / "event.json"
            if not parent_event.is_file():
                # Slurm may account for the child before the upstream watcher saves its event.
                deadline = time.monotonic() + 2 * upstream.get("poll_seconds", SLURM_POLL_SECONDS)
                while not parent_event.is_file() and time.monotonic() < deadline:
                    time.sleep(min(2, max(0, deadline - time.monotonic())))
            observed = read_json(parent_event)
            if not failed_before(observed, upstream["job_id"], end):
                break
        except (OSError, ValueError, KeyError):
            break
        visited.add(parent)
        root = (parent, observed)
        task, event = upstream, observed
    return root


def monitor_slurm(job, interval, wait_limit):
    deadline = time.monotonic() + wait_limit if wait_limit else None
    previous = None
    last_error = None
    while True:
        try:
            outcome = slurm_terminal(job)
            if outcome is not None and outcome == previous:
                return outcome
            previous = outcome
            last_error = None
        except (OSError, subprocess.TimeoutExpired, WatchError) as error:
            previous = None
            if str(error) != last_error:
                print(f"Slurm status unavailable: {error}", file=sys.stderr, flush=True)
            last_error = str(error)
        if deadline is not None and time.monotonic() >= deadline:
            return {"outcome": "unknown", "reason": last_error or "No confirmed Slurm terminal record"}
        time.sleep(interval)


def wait_child(command):
    try:
        child = subprocess.Popen(command)
    except OSError as error:
        return {"outcome": "failed_or_stopped", "spawn_error": str(error)}, 1

    def forward(signum, _):
        if child.poll() is None:
            child.send_signal(signum)

    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        code = child.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    outcome = "process_succeeded" if code == 0 else "failed_or_stopped"
    return {"outcome": outcome, "returncode": code}, 128 - code if code < 0 else code


def monitor(args, command):
    origin = origin_from(args)
    route = None if args.record_only else route_from(args)
    # Preflight belongs before submission. A socket outage here must not
    # prevent us from recording an already submitted job's terminal evidence.
    folder = Path(args.state_dir).resolve()
    plan = Path(args.plan).resolve(strict=True)
    if not plan.is_file():
        raise WatchError("The task plan must be an existing file")
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    with locked(folder, "watch.lock"):
        task_path = folder / "watch.json"
        event_path = folder / "event.json"
        task = {"route": route, "thread": origin, "plan": str(plan), "mode": args.action, "registered_at": now(),
                "cwd": os.getcwd(), "job_id": getattr(args, "job_id", None), "model_url": args.model_url}
        if args.action == "slurm":
            task["poll_seconds"] = args.poll_seconds
            if args.afterok_state_dir:
                upstream = Path(args.afterok_state_dir).resolve()
                if upstream == folder:
                    raise WatchError("The upstream monitor must have its own state directory")
                task["afterok_state_dir"] = str(upstream)
        if task_path.exists():
            saved = read_json(task_path)
            keys = ("mode", "plan", "job_id")
            saved_origin = saved.get("thread") or (saved["route"] or {}).get("thread")
            if (args.action != "slurm" or event_path.exists() or saved_origin != origin
                    or any(saved[key] != task[key] for key in keys)
                    or (task.get("afterok_state_dir") and task["afterok_state_dir"] != saved.get("afterok_state_dir"))):
                raise WatchError("This attempt already exists. Use deliver for a saved event or a new directory for a new attempt")
            task = saved
        else:
            save_json(task_path, task)
        if args.action == "run":
            evidence, code = wait_child(command)
        else:
            evidence = monitor_slurm(args.job_id, args.poll_seconds, args.wait_limit)
            code = int(evidence["outcome"] != "process_succeeded")
        event = make_event(evidence)
        save_json(event_path, event)
    try:
        dispatch(folder, task, event, args.delivery_seconds)
    except (WatchError, OSError) as error:
        print(f"Completion event saved for later delivery: {error}", file=sys.stderr)
    return code


def replay(args):
    folder = Path(args.state_dir).resolve(strict=True)
    task = read_json(folder / "watch.json")
    event = read_json(folder / "event.json")
    state = dispatch(folder, task, event, args.delivery_seconds)
    return int(state not in {"queued", "acknowledged"})


def acknowledge(args):
    folder = Path(args.state_dir).resolve(strict=True)
    task = read_json(folder / "watch.json")
    event = read_json(folder / "event.json")
    caller = thread_id(os.environ.get("CODEX_THREAD_ID"))
    expected = task.get("thread") or (task["route"] or {}).get("thread")
    if caller != expected or args.event != event["event_id"]:
        raise WatchError("Event ID or originating Codex thread does not match")
    with locked(folder, "ack.lock"):
        receipt = folder / "received.json"
        newly_received = not receipt.exists()
        if newly_received:
            save_json(receipt, {"thread": caller, "event_id": args.event, "acknowledged_at": now()})
    print(json.dumps({"acknowledged": True, "first_ack": newly_received, "event_id": args.event}))


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    routes = argparse.ArgumentParser(add_help=False)
    routes.add_argument("--codex", help="Override the Codex executable discovered on PATH")
    routes.add_argument("--socket", help="Override the control socket of the current CODEX_HOME")
    routes.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    state = argparse.ArgumentParser(add_help=False)
    state.add_argument("--state-dir", required=True)
    handoff = argparse.ArgumentParser(add_help=False)
    handoff.add_argument("--delivery-seconds", type=int, default=DELIVERY_SECONDS,
                         help="Maximum seconds to wait for an available routing path")
    registration = argparse.ArgumentParser(add_help=False)
    registration.add_argument("--record-only", action="store_true", help="Save exit evidence for later review")
    registration.add_argument("--model-url", help="Optional HTTPS model endpoint to check before queueing")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("probe", parents=[routes])
    run = sub.add_parser("run", parents=[routes, state, handoff, registration])
    run.add_argument("--plan", required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    slurm = sub.add_parser("slurm", parents=[routes, state, handoff, registration])
    slurm.add_argument("--plan", required=True)
    slurm.add_argument("--job-id", required=True)
    slurm.add_argument("--poll-seconds", type=int, default=SLURM_POLL_SECONDS)
    slurm.add_argument("--wait-limit", type=int, default=0, help="Maximum seconds to watch, or 0 to wait for a terminal record")
    slurm.add_argument("--afterok-state-dir", help="State directory of this job's single direct Slurm afterok prerequisite")
    sub.add_parser("deliver", parents=[state, handoff])
    ack = sub.add_parser("ack", parents=[state])
    ack.add_argument("--event", required=True)
    return parser, parser.parse_args()


def main():
    parser, args = arguments()
    if getattr(args, "delivery_seconds", 0) < 0:
        parser.error("--delivery-seconds must be nonnegative")
    try:
        if getattr(args, "model_url", None):
            endpoint = urlsplit(args.model_url)
            if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username is not None
                    or endpoint.query or endpoint.fragment):
                parser.error("--model-url requires an HTTPS URL without credentials, query, or fragment")
        if args.action == "probe":
            task_status(args)
        elif args.action == "ack":
            acknowledge(args)
        elif args.action == "deliver":
            return replay(args)
        elif args.action == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not command:
                parser.error("run requires a foreground command after --")
            return monitor(args, command)
        else:
            if not re.fullmatch(r"\d+(?:_\d+)?(?:\+\d+)?", args.job_id):
                parser.error("--job-id requires an exact Slurm job or array task ID")
            if args.poll_seconds < 1 or args.wait_limit < 0:
                parser.error("--poll-seconds must be positive and --wait-limit must be nonnegative")
            return monitor(args, None)
    except (OSError, ValueError, KeyError, WatchError) as error:
        print(f"watch-research-run: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
