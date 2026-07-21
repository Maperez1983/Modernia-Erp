#!/usr/bin/env python3
"""Python launcher for the F5 FD-inheritance diagnostic.

This wrapper launches Chrome directly with close_fds=True / pass_fds=()
and keeps its stdout/stderr drained so the parent Node process can attach
through DevTools while the wrapper remains alive.
"""

from __future__ import annotations

import argparse
import base64
import errno
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request


DIAGNOSTIC_REDACTED_VALUE = "REDACTED"
DIAGNOSTIC_OMIT_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "proxy-authorization",
    "set-cookie",
    "token",
}


def _to_text(value: Any) -> str:
    return "" if value is None else str(value)


def _monotonic_ms(started_at: float) -> float:
    return round((time.monotonic() - started_at) * 1000, 3)


def _write_json_record(stream, record: Dict[str, Any]) -> None:
    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    stream.flush()


def sanitizeDiagnosticValue(value: Any, key: str = "") -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [sanitizeDiagnosticValue(item, key) for item in value]
    if isinstance(value, tuple):
        return [sanitizeDiagnosticValue(item, key) for item in value]
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_key_lower = str(child_key or "").lower()
            if child_key_lower in DIAGNOSTIC_OMIT_KEYS:
                continue
            sanitized[child_key] = sanitizeDiagnosticValue(child_value, str(child_key))
        return sanitized
    if isinstance(value, str):
        return value
    return str(value)


def capture_proc_fd_listing(pid: int) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "pid": pid or None,
        "available": False,
        "count": 0,
        "entries": [],
        "error": "",
    }
    if not pid:
        snapshot["error"] = "missing pid"
        return snapshot
    if os.name != "posix" or not Path("/proc").exists():
        snapshot["error"] = "procfs unavailable"
        return snapshot

    fd_dir = Path("/proc") / str(pid) / "fd"
    try:
        entries = []
        for fd_name in sorted(os.listdir(fd_dir), key=lambda name: int(name)):
            fd_path = fd_dir / fd_name
            try:
                target = os.readlink(fd_path)
            except OSError as exc:  # pragma: no cover - defensive
                target = f"ERROR: {exc}"
            fd_info_path = Path("/proc") / str(pid) / "fdinfo" / fd_name
            fd_info = {
                "inode": None,
                "flags": "",
                "raw": "",
                "error": "",
            }
            try:
                fd_info_text = fd_info_path.read_text(encoding="utf-8")
                fd_info["raw"] = fd_info_text
                for line in fd_info_text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("flags:"):
                        fd_info["flags"] = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("ino:"):
                        try:
                            fd_info["inode"] = int(stripped.split(":", 1)[1].strip())
                        except ValueError:
                            fd_info["inode"] = None
            except OSError as exc:
                fd_info["error"] = str(exc)
            entries.append({"fd": int(fd_name), "target": target, "fdinfo": fd_info})
        snapshot["available"] = True
        snapshot["count"] = len(entries)
        snapshot["entries"] = entries
    except OSError as exc:
        snapshot["error"] = str(exc)
    return snapshot


def build_chrome_args(config: Dict[str, Any]) -> List[str]:
    chrome_path = _to_text(config.get("chromePath")).strip()
    if not chrome_path:
        raise ValueError("chromePath is required")
    launch_flags = [str(flag) for flag in config.get("launchFlags", []) if str(flag).strip()]
    profile_dir = _to_text(config.get("profileDir")).strip()
    if not profile_dir:
        raise ValueError("profileDir is required")
    return [chrome_path, *launch_flags, f"--user-data-dir={profile_dir}"]


def terminate_process_gracefully(proc: subprocess.Popen, grace_ms: int = 5000) -> None:
    try:
        if proc.poll() is not None:
            return
    except Exception:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=max(0.001, grace_ms / 1000))
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=max(0.001, grace_ms / 1000))
    except Exception:
        pass


def scrub_inherited_fd_descriptors(
    allow_list: Optional[List[int]] = None,
    *,
    capture_fd_listing_fn=capture_proc_fd_listing,
    process_impl=os,
) -> Dict[str, Any]:
    allowed = {int(fd) for fd in (allow_list or [0, 1, 2])}
    before = capture_fd_listing_fn(os.getpid())
    closed: List[Dict[str, Any]] = []
    if not before.get("available"):
        return {"before": before, "after": before, "closed": closed}

    for entry in before.get("entries", []):
        fd = int(entry.get("fd") or -1)
        if fd < 3 or fd in allowed:
            continue
        try:
            process_impl.close(fd)
            closed.append(
                {
                    "fd": fd,
                    "target": entry.get("target", ""),
                    "fdinfo": entry.get("fdinfo", {}),
                    "closed": True,
                    "reason": "inherited descriptor scrubbed before Chrome launch",
                }
            )
        except OSError as exc:
            if exc.errno == errno.EBADF:
                closed.append(
                    {
                        "fd": fd,
                        "target": entry.get("target", ""),
                        "fdinfo": entry.get("fdinfo", {}),
                        "closed": False,
                        "ignored": True,
                        "reason": "fd already closed before scrub",
                    }
                )
                continue
            closed.append(
                {
                    "fd": fd,
                    "target": entry.get("target", ""),
                    "fdinfo": entry.get("fdinfo", {}),
                    "closed": False,
                    "error": str(exc),
                    "reason": "failed to close inherited descriptor before Chrome launch",
                }
            )
    after = capture_fd_listing_fn(os.getpid())
    return {"before": before, "after": after, "closed": closed}


def _start_stream_drain(stream, chunks: List[str]) -> threading.Thread:
    def drain() -> None:
      try:
        for line in iter(stream.readline, ""):
          chunks.append(line)
      finally:
        try:
          stream.close()
        except Exception:
          pass

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    return thread


def read_devtools_active_port(profile_dir: str) -> Dict[str, Any]:
    active_port_path = Path(profile_dir) / "DevToolsActivePort"
    text = active_port_path.read_text(encoding="utf-8").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise RuntimeError("DevToolsActivePort inválido")
    port = int(lines[0])
    ws_path = lines[1]
    if not port or not ws_path:
        raise RuntimeError("DevToolsActivePort inválido")
    return {
        "filePath": str(active_port_path),
        "port": port,
        "wsPath": ws_path,
        "wsEndpoint": f"ws://127.0.0.1:{port}{ws_path}",
    }


def wait_for_devtools_active_port(profile_dir: str, proc: subprocess.Popen, timeout_ms: int = 30000) -> Dict[str, Any]:
    started_at = time.monotonic()
    while (time.monotonic() - started_at) * 1000 < timeout_ms:
        if proc.poll() is not None:
            raise RuntimeError("Chrome terminó antes de publicar DevToolsActivePort")
        try:
            devtools = read_devtools_active_port(profile_dir)
        except Exception:
            time.sleep(0.1)
            continue
        try:
            with urllib_request.urlopen(
                f"http://127.0.0.1:{devtools['port']}/json/version",
                timeout=1,
            ) as response:
                if 200 <= int(getattr(response, "status", 0) or 0) < 400:
                    return devtools
        except urllib_error.URLError:
            pass
        except Exception:
            pass
        try:
            with socket.create_connection(("127.0.0.1", int(devtools["port"])), timeout=1) as sock:
                ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
                request = (
                    f"GET {devtools['wsPath']} HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{int(devtools['port'])}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {ws_key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                )
                sock.sendall(request.encode("ascii"))
                sock.settimeout(1)
                response = sock.recv(4096).decode("latin1", "replace")
                if " 101 " in response and "Sec-WebSocket-Accept" in response:
                    return devtools
        except Exception:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"DevToolsActivePort no apareció dentro de {timeout_ms}ms")


def launch_chrome_process(
    config: Dict[str, Any],
    *,
    subprocess_module=subprocess,
    capture_fd_listing_fn=capture_proc_fd_listing,
) -> Dict[str, Any]:
    python_pid = os.getpid()
    python_fds_before = capture_fd_listing_fn(python_pid)
    scrub_inherited_fds = bool(config.get("scrubInheritedFds"))
    scrubbed_fds = (
        scrub_inherited_fd_descriptors(capture_fd_listing_fn=capture_fd_listing_fn)
        if scrub_inherited_fds
        else {"before": python_fds_before, "after": python_fds_before, "closed": []}
    )
    python_fds_after_scrub = scrubbed_fds["after"]
    chrome_args = build_chrome_args(config)
    proc = subprocess_module.Popen(
        chrome_args,
        close_fds=True,
        pass_fds=(),
        stdin=subprocess_module.DEVNULL,
        stdout=subprocess_module.PIPE,
        stderr=subprocess_module.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    stdout_thread = _start_stream_drain(proc.stdout, stdout_chunks)
    stderr_thread = _start_stream_drain(proc.stderr, stderr_chunks)

    devtools_timeout_ms = int(config.get("devtoolsTimeoutMs") or 30000)
    try:
        devtools = wait_for_devtools_active_port(_to_text(config.get("profileDir")), proc, devtools_timeout_ms)
    except Exception:
        terminate_process_gracefully(proc)
        raise
    python_fds_after = capture_fd_listing_fn(python_pid)
    chrome_fds_before = capture_fd_listing_fn(proc.pid)

    launch_info = {
        "phase": "launch",
        "pythonPid": python_pid,
        "pythonFdsBefore": python_fds_before,
        "pythonFdsBeforeScrub": python_fds_before,
        "pythonFdsAfterScrub": python_fds_after_scrub,
        "pythonFdsAfterLaunch": python_fds_after,
        "chromePid": proc.pid,
        "chromePath": _to_text(config.get("chromePath")),
        "browserWSEndpoint": devtools["wsEndpoint"],
        "devtoolsPort": devtools["port"],
        "devtoolsPath": devtools["wsPath"],
        "profileDir": _to_text(config.get("profileDir")),
        "devtoolsActivePort": devtools,
        "chromeFdsBeforeLaunch": chrome_fds_before,
        "chromeFdsAfterLaunch": chrome_fds_before,
        "launchFlags": [str(flag) for flag in config.get("launchFlags", []) if str(flag).strip()],
        "close_fds": True,
        "pass_fds": [],
        "scrubInheritedFds": scrub_inherited_fds,
        "bootstrapHelperTree": bool(config.get("bootstrapHelperTree")),
        "scrubbedFds": scrubbed_fds["closed"],
    }

    return {
        "proc": proc,
        "stdout_chunks": stdout_chunks,
        "stderr_chunks": stderr_chunks,
        "stdout_thread": stdout_thread,
        "stderr_thread": stderr_thread,
        "launch_info": launch_info,
        "python_pid": python_pid,
        "chrome_pid": proc.pid,
        "python_fds_before": python_fds_before,
        "python_fds_before_scrub": python_fds_before,
        "python_fds_after_scrub": python_fds_after_scrub,
        "python_fds_after": python_fds_after,
        "chrome_fds_before": chrome_fds_before,
        "config": config,
    }


def _signal_name(returncode: Optional[int]) -> Optional[str]:
    if returncode is None or returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except Exception:
        return f"SIG{-returncode}"


def wait_for_chrome_exit(
    state: Dict[str, Any],
    *,
    timeout_ms: Optional[int] = None,
    grace_ms: int = 5000,
    capture_fd_listing_fn=capture_proc_fd_listing,
) -> Dict[str, Any]:
    proc: subprocess.Popen = state["proc"]
    chrome_pid = state["chrome_pid"]
    timeout_seconds = None if timeout_ms is None else max(0.001, timeout_ms / 1000)
    grace_seconds = max(0.001, grace_ms / 1000)
    timed_out = False

    try:
        returncode = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            returncode = proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            returncode = proc.wait()

    state["stdout_thread"].join(timeout=1)
    state["stderr_thread"].join(timeout=1)

    python_fds_after_exit = capture_fd_listing_fn(state["python_pid"])
    chrome_fds_after_exit = capture_fd_listing_fn(chrome_pid)
    stdout_text = "".join(state["stdout_chunks"])
    stderr_text = "".join(state["stderr_chunks"])

    return {
        "phase": "complete",
        "pythonPid": state["python_pid"],
        "chromePid": chrome_pid,
        "chromeExitCode": returncode if returncode is not None and returncode >= 0 else None,
        "chromeExitSignal": _signal_name(returncode),
        "chromeTimedOut": timed_out,
        "pythonFdsAfterExit": python_fds_after_exit,
        "chromeFdsAfterExit": chrome_fds_after_exit,
        "chromeStdoutText": stdout_text,
        "chromeStderrText": stderr_text,
    }


def wait_for_close_command_or_exit(
    proc: subprocess.Popen,
    stdin_stream,
    *,
    poll_interval_ms: int = 100,
) -> Dict[str, Any]:
    command_queue: "queue.Queue[object]" = queue.Queue()
    stdin_eof_marker = object()

    def reader() -> None:
        try:
            for raw_line in iter(stdin_stream.readline, ""):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    command_queue.put(json.loads(line))
                except Exception:
                    continue
        finally:
            command_queue.put(stdin_eof_marker)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    while True:
        if proc.poll() is not None:
            return {
                "kind": "chrome-exit",
                "chromeExitCode": proc.returncode if proc.returncode is not None and proc.returncode >= 0 else None,
                "chromeExitSignal": _signal_name(proc.returncode),
            }
        try:
            command = command_queue.get(timeout=max(0.001, poll_interval_ms / 1000))
        except queue.Empty:
            continue
        if command is stdin_eof_marker:
            return {"kind": "stdin-eof"}
        if isinstance(command, dict) and command.get("command") == "close":
            return {
                "kind": "close",
                "command": command,
            }


def bootstrap_helper_tree(
    config: Dict[str, Any],
    *,
    subprocess_module=subprocess,
    stdin_stream=sys.stdin,
    stdout_stream=sys.stdout,
    stderr_stream=sys.stderr,
) -> int:
    """Launch a clean child copy of this helper with close_fds=True."""

    helper_script_path = Path(__file__).resolve()
    child_config = dict(config)
    child_config["bootstrapHelperTree"] = False
    child_args = [
        sys.executable,
        str(helper_script_path),
        "--bootstrap-child",
        f"--config-json={json.dumps(child_config, ensure_ascii=False)}",
    ]
    child = subprocess_module.Popen(
        child_args,
        close_fds=True,
        pass_fds=(),
        stdin=subprocess_module.PIPE,
        stdout=subprocess_module.PIPE,
        stderr=subprocess_module.PIPE,
        text=True,
        bufsize=1,
    )
    if child.stdin is None or child.stdout is None or child.stderr is None:
        raise RuntimeError("No se pudo inicializar el bootstrap limpio del helper.")

    def relay_input() -> None:
        try:
            for raw_line in iter(stdin_stream.readline, ""):
                try:
                    child.stdin.write(raw_line)
                    child.stdin.flush()
                except Exception:
                    break
        finally:
            try:
                child.stdin.close()
            except Exception:
                pass

    def relay_output(source_stream, destination_stream) -> None:
        try:
            for raw_line in iter(source_stream.readline, ""):
                try:
                    destination_stream.write(raw_line)
                    destination_stream.flush()
                except Exception:
                    break
        finally:
            try:
                source_stream.close()
            except Exception:
                pass

    input_thread = threading.Thread(target=relay_input, daemon=True)
    stdout_thread = threading.Thread(target=relay_output, args=(child.stdout, stdout_stream), daemon=True)
    stderr_thread = threading.Thread(target=relay_output, args=(child.stderr, stderr_stream), daemon=True)
    input_thread.start()
    stdout_thread.start()
    stderr_thread.start()
    try:
        return child.wait()
    finally:
        try:
            child.stdin.close()
        except Exception:
            pass
        input_thread.join(timeout=1)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)


def run_launcher(
    config: Dict[str, Any],
    *,
    subprocess_module=subprocess,
    capture_fd_listing_fn=capture_proc_fd_listing,
    stdin_stream=sys.stdin,
    stdout_stream=sys.stdout,
    started_at: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if started_at is None:
        started_at = time.monotonic()
    state = launch_chrome_process(
        config,
        subprocess_module=subprocess_module,
        capture_fd_listing_fn=capture_fd_listing_fn,
    )
    launch_info = state["launch_info"]
    launch_record = dict(launch_info)
    launch_record["phase"] = "launch_info"
    launch_record["monotonicMs"] = _monotonic_ms(started_at)
    _write_json_record(stdout_stream, launch_record)

    close_command = wait_for_close_command_or_exit(state["proc"], stdin_stream)
    if close_command.get("kind") in {"close", "stdin-eof"} and state["proc"].poll() is None:
        terminate_process_gracefully(state["proc"])

    complete_info = wait_for_chrome_exit(
        state,
        timeout_ms=int(config.get("completionTimeoutMs") or 600000),
        grace_ms=int(config.get("completionGraceMs") or 5000),
        capture_fd_listing_fn=capture_fd_listing_fn,
    )
    complete_record = dict(complete_info)
    complete_record["phase"] = "complete_info"
    complete_record["monotonicMs"] = _monotonic_ms(started_at)
    complete_record["closeCommand"] = sanitizeDiagnosticValue(close_command)
    _write_json_record(stdout_stream, complete_record)
    return launch_record, complete_record


def _load_config(argv: List[str]) -> Dict[str, Any]:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--config-json", dest="config_json")
    parser.add_argument("--config-file", dest="config_file")
    parser.add_argument("--scrub-inherited-fds", dest="scrub_inherited_fds", action="store_true")
    parser.add_argument("--bootstrap-helper-tree", dest="bootstrap_helper_tree", action="store_true")
    parser.add_argument("--bootstrap-child", dest="bootstrap_child", action="store_true")
    args, _ = parser.parse_known_args(argv)

    config_text = ""
    if args.config_json:
        config_text = args.config_json
    elif args.config_file:
        config_text = Path(args.config_file).read_text(encoding="utf-8")
    elif os.environ.get("LHCI_FD_MATRIX_CONFIG"):
        config_text = os.environ["LHCI_FD_MATRIX_CONFIG"]

    if not config_text:
        raise RuntimeError("Falta la configuración JSON para chrome_clean_launcher.py")

    config = json.loads(config_text)
    if args.scrub_inherited_fds:
        config["scrubInheritedFds"] = True
    if args.bootstrap_helper_tree:
        config["bootstrapHelperTree"] = True
    config["bootstrapChild"] = bool(args.bootstrap_child)
    return config


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    started_at = time.monotonic()
    try:
        config = _load_config(argv)
        if config.get("bootstrapHelperTree") and not config.get("bootstrapChild"):
            return bootstrap_helper_tree(config)
        run_launcher(config, started_at=started_at)
        return 0
    except Exception as exc:
        error_record = {
            "phase": "error",
            "message": str(exc),
            "monotonicMs": _monotonic_ms(started_at),
        }
        try:
            _write_json_record(sys.stdout, error_record)
        except Exception:
            pass
        try:
            sys.stderr.write(f"{exc}\n")
            sys.stderr.flush()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
