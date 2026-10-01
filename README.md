# ⚡ Python Service Manager

<p align="center">
  <strong>A modern, full-featured web-based Linux system administration & microservice orchestration dashboard built with Flask, Socket.IO, Systemd, and Docker.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/Flask-3.0.3-black?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/Socket.IO-Realtime-010101?style=for-the-badge&logo=socketdotio&logoColor=white" alt="Socket.IO">
  <img src="https://img.shields.io/badge/Docker-Containers-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Linux-Systemd-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux Systemd">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License">
</p>

---

## 🌟 Overview

**Python Service Manager** provides an intuitive web interface for managing Linux system services, background Python daemons, Docker containers, firewall rules, live server telemetry, and interactive web terminal sessions.

Whether you run multiple web applications, background worker queues, or containerized stacks on VPS or bare-metal servers, this tool centralizes management into a single responsive control plane.

---

## 🚀 Key Features

- 🖥️ **Live System Metrics & Telemetry**: Real-time CPU, RAM, disk usage, uptime, active process counts, and historical load graphs.
- ⚙️ **Systemd & Python Service Management**:
  - Automatically generate, enable, disable, start, stop, and restart Systemd `.service` units.
  - Configure custom Python virtual environments (`venv`), environment variables, autostart, and restart policies.
  - Live log streaming with journalctl integration.
  - Interactive file browser modal for picking working directories and Python entrypoints.
- 🐳 **Docker & Container Orchestration**:
  - Live container inspection, real-time status monitoring, CPU/Memory telemetry per container.
  - One-click Start, Stop, Restart, and live container log viewers.
  - Docker Compose stack discovery and status tracking.
- 🔥 **UFW Firewall Manager**:
  - View active firewall rules, open/close ports (TCP/UDP), and toggle firewall status directly from the UI.
- 🌐 **Network Port Checker**:
  - Instant live port listening status checker to diagnose port binding conflicts.
- 💻 **Web Terminal & SSH Client**:
  - Full-featured, in-browser pseudo-terminal (PTY) backed by Paramiko and WebSockets with xterm-like interactivity.
- 🔒 **Security & Authentication**:
  - Session-based authentication with configurable master password and password protection.

---

## 📂 Project Architecture

```
python-service-manager/
├── app.py                   # Main Flask & Socket.IO server entrypoint
├── config.py                # Configuration loader & persistent settings manager
├── monitor.py               # Background daemon for real-time CPU/RAM/Network telemetry
├── service_manager.py       # Custom service catalog & Systemd unit generation
├── systemd.py               # Systemd subprocess bindings, journalctl log stream & parser
├── docker_manager.py        # Docker Engine SDK & CLI wrapper for container management
├── firewall_manager.py      # UFW (Uncomplicated Firewall) rules parser and manager
├── utils.py                 # System info, directory browser, and port check helpers
├── requirements.txt         # Python package dependencies
├── services.example.json    # Sample service catalog template
├── settings.example.json    # Sample settings template
├── static/                  # CSS stylesheets, JS scripts, and brand assets
│   ├── css/style.css
│   ├── js/main.js
│   └── img/
└── templates/               # Jinja2 UI templates
    ├── base.html
    ├── dashboard.html
    ├── create.html
    ├── edit.html
    ├── docker.html
    ├── logs.html
    ├── terminal.html
    ├── port_checker.html
    ├── settings.html
    └── login.html
```

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- Linux OS (Ubuntu 20.04+, Debian 11+, CentOS/RHEL 8+)
- Python 3.9 or newer
- `systemd`, `docker` (optional), `ufw` (optional)
- Sudo/Root privileges for systemd and firewall controls

### 2. Clone the Repository
```bash
git clone https://github.com/ShriyashBPatil/python-service-manager.git
cd python-service-manager
```

### 3. Create a Virtual Environment & Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configuration
Create your initial configuration files from the provided templates:
```bash
cp settings.example.json settings.json
cp services.example.json services.json
```
Edit `settings.json` to configure your dashboard password and defaults.

### 5. Run the Application
```bash
python3 app.py
```
By default, the server runs on `http://0.0.0.0:5000`.

---

## 🛡️ Running as a Systemd Service

To keep Python Service Manager running automatically in the background across reboots:

1. Create `/etc/systemd/system/python-service-manager.service`:
```ini
[Unit]
Description=Python Service Manager Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/python-service-manager
ExecStart=/path/to/python-service-manager/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

2. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable python-service-manager
sudo systemctl start python-service-manager
```

---

## 📜 License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

## 👨‍💻 Author

**SHRIYASH PATIL**
- GitHub: [@ShriyashBPatil](https://github.com/ShriyashBPatil)
- Website: [shriyashpatil.in](https://shriyashpatil.in)
