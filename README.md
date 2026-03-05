# SimpleProxy

A lightweight HTTP/HTTPS proxy with a Windows system tray icon.
No HTTPS interception — HTTPS is tunneled blindly. No bloat. Just works.

---

## Features

- HTTP and HTTPS proxy on port 8080 (configurable)
- HTTPS via blind CONNECT tunneling — encrypted traffic is never inspected
- IP allowlist — denied IPs are refused at the socket level (silent drop)
- Live config reload — edit config.json and changes apply within ~1 second
- System tray icon with: Open Log, Start with Windows toggle, Exit
- Rolling log file — last 60 minutes (configurable)
- Single .exe, no installer needed

---

## Quick Start (from source)

1. Install Python 3.10+ from https://python.org
2. Open a terminal in this folder and run:

```
pip install -r requirements.txt
pythonw proxy.py
```

A green circle icon will appear in your system tray.

---

## Building the .exe

1. Install Python 3.10+ (make sure it's in your PATH)
2. Double-click `build.bat`
3. Your executable lands in `dist\SimpleProxy.exe`
4. Copy `dist\SimpleProxy.exe` and `dist\config.json` wherever you want to run it from
5. Run `SimpleProxy.exe` — it registers itself to start with Windows automatically

---

## Configuration (config.json)

```json
{
  "port": 8080,
  "allowed_ips": ["192.168.1.10", "192.168.1.50"],
  "log_retention_minutes": 60
}
```

| Key                    | Default | Description                                         |
|------------------------|---------|-----------------------------------------------------|
| port                   | 8080    | Port the proxy listens on                           |
| allowed_ips            | []      | Whitelist of client IPs. Empty = allow all.         |
| log_retention_minutes  | 60      | How many minutes of log history to keep in memory   |

**allowed_ips behaviour:**
- `[]` (empty array) = all IPs allowed (open mode, useful for testing)
- Any entries present = only those exact IPs are allowed, everything else is silently refused

Changes to config.json take effect within ~1 second. No restart needed.

---

## Log format

```
2026-03-05 09:14:22 | ALLOW | 192.168.1.10 | GET example.com:80/
2026-03-05 09:14:23 | ALLOW | 192.168.1.10 | CONNECT example.com:443
2026-03-05 09:14:24 | DENY  | 10.0.0.5     | connection refused
2026-03-05 09:14:25 | CONFIG | Loaded: port=8080, allowed_ips=['192.168.1.10'], retention=60m
```

Open the log at any time from the tray icon → Open Log (opens in Notepad).

---

## Configuring clients to use the proxy

Set HTTP proxy to:
- Host: the IP of the machine running SimpleProxy (or 127.0.0.1 if local)
- Port: 8080 (or whatever you set in config.json)

### curl examples
```
curl.exe -x http://127.0.0.1:8080 http://example.com
curl.exe -x http://127.0.0.1:8080 https://example.com
```

Note: In PowerShell, always use `curl.exe` (not `curl`) to get real curl rather than the Invoke-WebRequest alias.

### PowerShell native
```powershell
Invoke-WebRequest -Uri "https://example.com" -Proxy "http://127.0.0.1:8080"
```

### Windows system-wide
Settings → Network & Internet → Proxy → Manual proxy setup
- Address: 127.0.0.1
- Port: 8080

---

## Tray Menu

| Item                  | Action                                              |
|-----------------------|-----------------------------------------------------|
| Open Log              | Flushes and opens proxy.log in Notepad              |
| ✓ Start with Windows  | Toggles the Windows startup registry entry          |
| Exit                  | Shuts down the proxy and removes the tray icon      |

---

## Troubleshooting

**Port already in use:** Another process is on port 8080. Change `port` in config.json.

**Connections not going through:** Check that the client IP is in `allowed_ips`, or set `allowed_ips` to `[]` temporarily to confirm it's an IP filtering issue.

**Log not updating:** The log file is only written when entries are added. If there's no traffic, the file won't change.

**curl in PowerShell not working:** Use `curl.exe` instead of `curl` — PowerShell's `curl` is an alias for Invoke-WebRequest and uses different syntax.
