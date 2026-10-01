import json
import os
import subprocess
import psutil
from config import SERVICES_FILE
from systemd import (write_systemd_file, delete_systemd_file, daemon_reload, 
                     enable_service, start_service, stop_service, restart_service, disable_service, check_service_status)


_cached_services_data = None
_services_mtime = 0

def load_services():
    global _cached_services_data, _services_mtime
    if not os.path.exists(SERVICES_FILE):
        return []
    try:
        mtime = os.path.getmtime(SERVICES_FILE)
        if _cached_services_data is not None and mtime == _services_mtime:
            return [dict(s) for s in _cached_services_data]
        with open(SERVICES_FILE, "r") as f:
            data = json.load(f)
            _cached_services_data = data.get("services", [])
            _services_mtime = mtime
            return [dict(s) for s in _cached_services_data]
    except Exception:
        return [dict(s) for s in (_cached_services_data or [])]

def save_services(services):
    global _cached_services_data, _services_mtime
    with open(SERVICES_FILE, "w") as f:
        json.dump({"services": services}, f, indent=2)
    _cached_services_data = services
    try:
        _services_mtime = os.path.getmtime(SERVICES_FILE)
    except Exception:
        pass

def generate_systemd_content(service_data):
    """Generate the contents of the systemd .service file."""
    name = service_data.get('name', 'unknown')
    desc = service_data.get('description', 'Python Service')
    user = service_data.get('user', 'root')
    work_dir = service_data.get('working_dir', '')
    venv = service_data.get('venv', '')
    py_file = service_data.get('python_file', '')
    restart = service_data.get('restart', 'always')
    env_vars = service_data.get('env_vars', '')
    
    if venv:
        exec_start = f"{os.path.join(venv, 'bin', 'python')} {py_file}"
    elif py_file.endswith('.py'):
        exec_start = f"python3 {py_file}"
    else:
        exec_start = py_file
    
    content = f"[Unit]\nDescription={desc}\nAfter=network.target\n\n[Service]\nUser={user}\n"
    if work_dir:
        content += f"WorkingDirectory={work_dir}\n"
    content += f"ExecStart={exec_start}\nRestart={restart}\n"
    content += "StandardOutput=journal\nStandardError=journal\nEnvironment=\"PYTHONUNBUFFERED=1\"\n"
    
    if env_vars:
        for line in env_vars.split('\n'):
            line = line.strip()
            if line:
                content += f"Environment=\"{line}\"\n"
                
    content += "\n[Install]\nWantedBy=multi-user.target\n"
    return content

def create_service(data):
    """Create a new service: write file, load, enable, start."""
    services = load_services()
    name = data['name']
    
    # Check if exists
    for s in services:
        if s['name'] == name:
            return False, "Service with this name already exists."
    
    # Write systemd file
    content = generate_systemd_content(data)
    success, msg = write_systemd_file(name, content)
    if not success:
        return False, f"Failed to write service file: {msg}"
        
    # Reload daemon
    daemon_reload()
    
    if data.get('autostart'):
        enable_service(name)
        start_service(name)
        
    # Save to JSON
    services.append(data)
    save_services(services)
    return True, "Service created successfully."

def update_service(name, data):
    services = load_services()
    for idx, s in enumerate(services):
        if s['name'] == name:
            services[idx] = data
            content = generate_systemd_content(data)
            success, msg = write_systemd_file(name, content)
            if not success:
                return False, f"Failed to rewrite service file: {msg}"
            
            daemon_reload()
            restart_service(name)
            
            save_services(services)
            return True, "Service updated successfully."
    return False, "Service not found."

def delete_service(name):
    services = load_services()
    new_services = [s for s in services if s['name'] != name]
    if len(services) == len(new_services):
        return False, "Service not found."
    
    stop_service(name)
    disable_service(name)
    delete_systemd_file(name)
    daemon_reload()
    
    save_services(new_services)
    return True, "Service deleted successfully."

def get_service_details():
    services = load_services()
    if not services:
        return []
    
    # Check status and batch query systemd properties if on Linux
    if os.name == 'posix':
        unit_names = [f"{s['name']}.service" for s in services]
        service_props = {}
        try:
            res = subprocess.run(
                ['systemctl', 'show', *unit_names, '-p', 'Id,ActiveState,MainPID,MemoryCurrent'],
                capture_output=True, text=True, timeout=2
            )
            current_data = {}
            for block in res.stdout.strip().split('\n\n'):
                data = {}
                for line in block.splitlines():
                    if '=' in line:
                        k, v = line.split('=', 1)
                        data[k.strip()] = v.strip()
                if 'Id' in data:
                    svc_id = data['Id'].replace('.service', '')
                    service_props[svc_id] = data
        except Exception:
            service_props = {}

        for s in services:
            props = service_props.get(s['name'], {})
            if props:
                s['is_running'] = (props.get('ActiveState') == 'active')
                main_pid = int(props.get('MainPID', 0)) if props.get('MainPID', '').isdigit() else 0
                mem_bytes = int(props.get('MemoryCurrent', 0)) if props.get('MemoryCurrent', '').isdigit() else 0
            else:
                s['is_running'] = check_service_status(s['name'])
                main_pid = 0
                mem_bytes = 0

            s['cpu'] = "0.0%"
            s['mem'] = "0MB"

            if s['is_running']:
                if mem_bytes > 0:
                    s['mem'] = f"{round(mem_bytes / (1024 * 1024), 1)}MB"
                if main_pid > 0 and psutil.pid_exists(main_pid):
                    try:
                        proc = psutil.Process(main_pid)
                        cpu = proc.cpu_percent(interval=None)
                        for child in proc.children(recursive=True):
                            try:
                                cpu += child.cpu_percent(interval=None)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        s['cpu'] = f"{round(cpu, 1)}%"
                        if mem_bytes == 0:
                            rss = proc.memory_info().rss
                            for child in proc.children(recursive=True):
                                try:
                                    rss += child.memory_info().rss
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass
                            s['mem'] = f"{round(rss / (1024 * 1024), 1)}MB"
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
    else:
        for s in services:
            s['is_running'] = False
            s['cpu'] = "0.0%"
            s['mem'] = "0MB"

    return services

