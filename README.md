<div align="center">

# 🔭 NetWatch

**Real-time process-level network monitor for Windows**

See all the connections to the internet — where they're connecting, who owns those servers, and how much data they're moving.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows&logoColor=white)

</div>

---

<img width="1916" height="541" alt="image" src="https://github.com/user-attachments/assets/eac00730-c726-49b6-921c-9270cb1df7a0" />

---

## What It Does

NetWatch sits somewhere between `netstat` and Wireshark — but focused on **clarity, not raw packet data**. It answers the questions that matter:

- Which apps are using my internet right now?
- What servers are they connecting to?
- Which organization owns those servers?
- How much data is each process sending and receiving?

---

## Features

| | |
|---|---|
| **Process attribution** | Every connection mapped to a process name and PID |
| **Remote IP & hostname** | See the server each app is talking to, resolved in the background |
| **IP ownership lookup** | Organization and country for every remote IP via ip-api.com |
| **Live bandwidth** | Per-process download / upload rates, refreshed every 2 seconds |
| **Filter bar** | Search instantly by process, IP, domain, or organization |
| **Sortable columns** | Click any column header to sort ascending or descending |
| **Right-click menu** | Copy IP, domain, organization, or process name to clipboard |
| **Filter shortcuts** | Right-click → filter by this process / IP / organization |
| **Admin warning** | Non-intrusive banner shown only when not running as Administrator |

---

## How to run

### Option 1: Download the .exe

Head to the [Releases](../../releases) page and download NetWatch.exe from the latest release. Run it directly — no installation required.

### Option 2: Run from source

```bash
pip install psutil requests
python netwatch_gui.py
```

### Option 3: Build a standalone `.exe`

```bash
pip install pyinstaller psutil requests
python build.py
```

Output: `dist/NetWatch.exe` — open the .exe file to run.

> **Note:** Run as Administrator for complete connection visibility.

---

## Requirements

| Dependency | Purpose |
|---|---|
| `psutil` | Process list, network connections, I/O counters |
| `requests` | IP lookup API calls |
| `tkinter` | GUI — included with Python, no install needed |

**Python 3.9 or higher required.**

---

## How It Works

```
psutil.net_connections()
        │
        ▼
map socket → process name + PID
        │
        ▼
filter private IPs  (RFC 1918, loopback, link-local, CG-NAT)
        │
        ▼
async reverse DNS + ip-api.com org lookup  (cached per IP)
        │
        ▼
psutil io_counters delta → per-process bandwidth rates
        │
        ▼
tkinter Treeview  —  refreshed every 2 seconds
```

IP lookups run on background threads and are cached in memory — each unique IP is queried only once per session.

---

## Limitations

- **Bandwidth is per-process**, not per-connection. A process with multiple active connections shows one combined rate.
- **Some connections show as `svchost` or `System`** — this reflects how Windows attributes connections at the kernel level, not a bug in NetWatch.
- **IP data via ip-api.com** (free tier, 45 req/min). On very active machines the first refresh may show some missing org info while lookups catch up — the cache fills quickly.

---

## Roadmap

- [ ] Connection history log with timestamps
- [ ] Suspicious connection detection — unknown processes, unusual geographies
- [ ] Per-connection bandwidth breakdown
- [ ] Persistent IP cache across sessions
- [ ] Export connections to CSV
- [ ] System tray mode

---

