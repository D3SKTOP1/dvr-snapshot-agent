# DVR Snapshot Agent

**A Windows agent that turns a regular CCTV recorder into a data source.** It connects to Intelbras DVRs (MHDX line) on the local network, captures JPEG snapshots from each camera and stores them on disk or ships them to a cloud ingestion API — optionally only when the DVR reports motion.

Built at SolverCam to feed computer-vision pipelines from cameras customers already own, without replacing any hardware.

---

## Features

- Periodic snapshot capture over HTTP Digest Auth (`/cgi-bin/snapshot.cgi`)
- **Motion-triggered mode** — polls the DVR alarm CGI and only captures when there is real movement
- Two storage backends: **local folder** (`cam01/cam01_YYYYMMDD_HHMMSS.jpg`) or **HTTPS API** (Base64 + API key)
- **Desktop monitor** (Tkinter): live camera table with status, file size and latency, colored log, start/pause, settings form, "test connection" and "test alarm" diagnostics
- Runs headless as a background service (Windows Task Scheduler), restarts on failure
- One-click installer (PyInstaller + Inno Setup), no admin rights needed

## How it works

```
dvr_monitor (Tkinter UI thread)  ◄── queue ──  AgentWorker thread
                                                 ├─ query_alarm()   → /cgi-bin/alarm.cgi
                                                 ├─ capture()       → /cgi-bin/snapshot.cgi
                                                 └─ store()         → local disk | ingestion API
```

The UI and the capture loop run on separate threads and talk through a queue polled every 80 ms, so a slow DVR never freezes the interface.

More detail: [docs/architecture.txt](docs/architecture.txt) · [docs/how-it-works-pt.md](docs/how-it-works-pt.md) (Portuguese)

## Run from source

```bash
pip install requests
python dvr_agent.py      # headless agent
python dvr_monitor.py    # desktop monitor
```

Configure DVR IP, port, credentials, interval, storage mode and cameras from the monitor's settings screen.

**Stack:** Python · requests · Tkinter · threading · PyInstaller · Inno Setup

---

Built by **Vitor Portela** — [LinkedIn](https://www.linkedin.com/in/mvitorportela/)
