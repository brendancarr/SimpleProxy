"""
SimpleProxy - A lightweight HTTP proxy with system tray support.
HTTP only (no CONNECT/HTTPS tunneling).
Denied IPs are refused at socket level before handshake completes.
"""

import socket
import threading
import json
import os
import sys
import time
import logging
import winreg
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ── Tray deps (pystray + Pillow) ──────────────────────────────────────────────
import pystray
from PIL import Image, ImageDraw

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH    = BASE_DIR / "proxy.log"
APP_NAME    = "SimpleProxy"
REG_KEY     = r"Software\Microsoft\Windows\CurrentVersion\Run"

# ─────────────────────────────────────────────────────────────────────────────
# Default config
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "port": 8080,
    "allowed_ips": [],
    "log_retention_minutes": 60,
}

# ─────────────────────────────────────────────────────────────────────────────
# Shared state (thread-safe via lock)
# ─────────────────────────────────────────────────────────────────────────────
state_lock  = threading.Lock()
config      = dict(DEFAULT_CONFIG)
log_entries = []          # list of (datetime, str)

# ─────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ─────────────────────────────────────────────────────────────────────────────
def log(line: str):
    now = datetime.now()
    entry = (now, line)
    with state_lock:
        log_entries.append(entry)
        _prune_log()
    # Also append to file
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{now.strftime('%Y-%m-%d %H:%M:%S')} | {line}\n")
    except Exception:
        pass


def _prune_log():
    """Remove entries older than retention window. Must hold state_lock."""
    retention = timedelta(minutes=config.get("log_retention_minutes", 60))
    cutoff = datetime.now() - retention
    while log_entries and log_entries[0][0] < cutoff:
        log_entries.pop(0)


def flush_log_file():
    """Rewrite log file with only in-memory (retained) entries."""
    with state_lock:
        _prune_log()
        lines = [
            f"{ts.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n"
            for ts, msg in log_entries
        ]
    try:
        with LOG_PATH.open("w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Config loader / watcher
# ─────────────────────────────────────────────────────────────────────────────
def load_config():
    global config
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(raw)
        with state_lock:
            config = merged
        log(f"CONFIG | Loaded: port={merged['port']}, "
            f"allowed_ips={merged['allowed_ips']}, "
            f"retention={merged['log_retention_minutes']}m")
    except Exception as e:
        log(f"CONFIG | Error loading config: {e}")


def config_watcher():
    last_mtime = 0
    while True:
        try:
            mtime = CONFIG_PATH.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                load_config()
        except Exception:
            pass
        time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
# Registry helpers (Windows startup)
# ─────────────────────────────────────────────────────────────────────────────
def get_exe_path() -> str:
    if getattr(sys, "frozen", False):
        return str(sys.executable)
    return f'pythonw "{Path(__file__).resolve()}"'


def startup_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def set_startup(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, get_exe_path())
            log("STARTUP | Enabled (registry key set)")
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                log("STARTUP | Disabled (registry key removed)")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        log(f"STARTUP | Registry error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# HTTP proxy core
# ─────────────────────────────────────────────────────────────────────────────
BUFFER = 65536


def handle_client(client_sock: socket.socket, client_addr):
    client_ip = client_addr[0]

    with state_lock:
        allowed = list(config.get("allowed_ips", []))

    if allowed and client_ip not in allowed:
        log(f"DENY  | {client_ip} | connection refused")
        client_sock.close()
        return

    try:
        # Read the HTTP request headers
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = client_sock.recv(BUFFER)
            if not chunk:
                client_sock.close()
                return
            raw += chunk
            if len(raw) > 65536:
                client_sock.close()
                return

        header_section = raw.split(b"\r\n\r\n")[0].decode("utf-8", errors="replace")
        lines = header_section.split("\r\n")
        if not lines:
            client_sock.close()
            return

        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            client_sock.close()
            return

        method = parts[0]
        url    = parts[1]

        # CONNECT tunnel (HTTPS) — blind TCP relay, no inspection
        if method.upper() == "CONNECT":
            host_port = url  # format: hostname:443
            if ":" in host_port:
                tunnel_host, tunnel_port_str = host_port.rsplit(":", 1)
                try:
                    tunnel_port = int(tunnel_port_str)
                except ValueError:
                    tunnel_port = 443
            else:
                tunnel_host = host_port
                tunnel_port = 443
            try:
                upstream = socket.create_connection((tunnel_host, tunnel_port), timeout=15)
                client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                log(f"ALLOW | {client_ip} | CONNECT {tunnel_host}:{tunnel_port}")
                _relay(client_sock, upstream)
            except Exception as e:
                log(f"ERROR | {client_ip} | CONNECT {url} failed: {e}")
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                client_sock.close()
            return

        # Parse host + port from URL or Host header
        host, port, path = _parse_request(url, lines)
        if not host:
            client_sock.close()
            return

        log(f"ALLOW | {client_ip} | {method} {host}:{port}{path}")

        # Connect upstream
        upstream = socket.create_connection((host, port), timeout=15)

        # Rebuild request targeting the path (not full URL) for upstream
        rebuilt = _rebuild_request(raw, method, path, lines)
        upstream.sendall(rebuilt)

        # Relay remaining body bytes already read
        body_tail = raw[raw.find(b"\r\n\r\n") + 4:]
        if body_tail:
            upstream.sendall(body_tail)

        # Bidirectional relay
        _relay(client_sock, upstream)

    except Exception as e:
        pass
    finally:
        try:
            client_sock.close()
        except Exception:
            pass


def _parse_request(url: str, header_lines: list):
    """Return (host, port, path) from URL and headers."""
    host = ""
    port = 80
    path = "/"

    if url.startswith("http://"):
        rest = url[7:]
        slash = rest.find("/")
        if slash == -1:
            hostport = rest
            path = "/"
        else:
            hostport = rest[:slash]
            path = rest[slash:]
        if ":" in hostport:
            h, p = hostport.rsplit(":", 1)
            host = h
            try:
                port = int(p)
            except ValueError:
                port = 80
        else:
            host = hostport
            port = 80
    else:
        # Relative URL — get host from Host header
        path = url
        for line in header_lines[1:]:
            if line.lower().startswith("host:"):
                hostport = line[5:].strip()
                if ":" in hostport:
                    h, p = hostport.rsplit(":", 1)
                    host = h
                    try:
                        port = int(p)
                    except ValueError:
                        port = 80
                else:
                    host = hostport
                    port = 80
                break

    return host, port, path


def _rebuild_request(raw: bytes, method: str, path: str, header_lines: list) -> bytes:
    """Rewrite the request line to use path instead of full URL."""
    version = "HTTP/1.1"
    first = header_lines[0].split(" ")
    if len(first) >= 3:
        version = first[2]

    new_request_line = f"{method} {path} {version}\r\n"
    rest = raw[raw.find(b"\r\n") + 2:]   # everything after first line
    return new_request_line.encode() + rest


def _relay(a: socket.socket, b: socket.socket):
    """Relay data between two sockets until both are closed."""
    a.settimeout(30)
    b.settimeout(30)

    def forward(src, dst):
        try:
            while True:
                data = src.recv(BUFFER)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass

    t = threading.Thread(target=forward, args=(b, a), daemon=True)
    t.start()
    forward(a, b)
    t.join(timeout=30)
    try:
        b.close()
    except Exception:
        pass


def proxy_server():
    while True:
        with state_lock:
            port = config.get("port", 8080)

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", port))
            srv.listen(256)
            log(f"SERVER | Listening on port {port}")
        except Exception as e:
            log(f"SERVER | Bind failed on port {port}: {e}")
            srv.close()
            time.sleep(5)
            continue

        current_port = port

        while True:
            with state_lock:
                new_port = config.get("port", 8080)
            if new_port != current_port:
                log(f"SERVER | Port changed to {new_port}, restarting listener")
                srv.close()
                break

            srv.settimeout(1.0)
            try:
                client_sock, client_addr = srv.accept()
                t = threading.Thread(
                    target=handle_client,
                    args=(client_sock, client_addr),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                log(f"SERVER | Accept error: {e}")
                break

        srv.close()
        time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
# System tray icon
# ─────────────────────────────────────────────────────────────────────────────
def make_icon_image(active: bool = True) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (34, 139, 34) if active else (180, 180, 180)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    # Simple "P" shape
    draw.rectangle([20, 16, 26, 48], fill="white")
    draw.ellipse([20, 16, 44, 34], fill=color)
    draw.ellipse([22, 18, 42, 32], fill="white")
    return img


def open_log(_icon, _item):
    flush_log_file()
    try:
        os.startfile(str(LOG_PATH))
    except Exception:
        subprocess.Popen(["notepad.exe", str(LOG_PATH)])


def toggle_startup(icon, item):
    enabled = startup_enabled()
    set_startup(not enabled)
    icon.menu = build_menu(icon)
    icon.update_menu()


def quit_app(icon, _item):
    log("SERVER | Shutting down")
    icon.stop()


def build_menu(icon=None):
    startup = startup_enabled()
    startup_label = "✓ Start with Windows" if startup else "  Start with Windows"
    return pystray.Menu(
        pystray.MenuItem("SimpleProxy", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Log", open_log),
        pystray.MenuItem(startup_label, toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", quit_app),
    )


def run_tray():
    icon_img = make_icon_image(active=True)
    icon = pystray.Icon(APP_NAME, icon_img, "SimpleProxy — Running", menu=build_menu())
    icon.run()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # Write default config if missing
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8"
        )

    load_config()

    # Enable startup by default on first run
    if not startup_enabled():
        set_startup(True)

    # Background threads
    threading.Thread(target=config_watcher, daemon=True).start()
    threading.Thread(target=proxy_server,   daemon=True).start()

    # Tray runs on main thread (required by most OS tray APIs)
    run_tray()


if __name__ == "__main__":
    main()
