import time
import threading
import psutil
import platform
import datetime
from collections import deque
import docker_manager
from service_manager import load_services
from systemd import check_service_status
import subprocess
import os

# Thread-safe ring buffer for time-series metrics
HISTORY_MAX_POINTS = 30
system_history = deque(maxlen=HISTORY_MAX_POINTS)
# Per-app history dictionaries
service_history = {}  # { service_name: deque(maxlen=30) of {time, cpu, mem_mb} }
container_history = {} # { container_id: deque(maxlen=30) of {time, cpu, mem_mb} }

cached_system_info = {}
cached_services = []
cached_docker_summary = {}
cached_docker_apps = []

# Background thread lock
_lock = threading.Lock()

def get_live_system_info():
    """Fast non-blocking system info retrieval."""
    with _lock:
        if cached_system_info:
            return cached_system_info.copy()
            
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.datetime.now() - boot_time
    disk = psutil.disk_usage('/')
    cpu_pct = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    return {
        "hostname": platform.node(),
        "os": platform.system() + " " + platform.release(),
        "kernel": platform.version(),
        "python_version": platform.python_version(),
        "cpu_usage": f"{cpu_pct:.1f}%",
        "cpu_raw": cpu_pct,
        "memory_usage": f"{mem.percent}%",
        "memory_raw": mem.percent,
        "mem_used_gb": round(mem.used / (1024**3), 2),
        "mem_total_gb": round(mem.total / (1024**3), 2),
        "disk_usage": f"{disk.percent}% ({disk.used // (2**30)}GB / {disk.total // (2**30)}GB)",
        "uptime": str(uptime).split('.')[0]
    }

def get_cached_services():
    with _lock:
        return [dict(s) for s in cached_services]

def get_cached_docker():
    with _lock:
        return dict(cached_docker_summary)

def get_cached_docker_apps():
    with _lock:
        return [dict(a) for a in cached_docker_apps]

def get_metrics_history():
    with _lock:
        # Convert deques to lists for json serialization
        svc_hist = {k: list(v) for k, v in service_history.items()}
        cnt_hist = {k: list(v) for k, v in container_history.items()}
        return {
            "system": list(system_history),
            "services": svc_hist,
            "containers": cnt_hist
        }

def _background_sampler():
    """Dedicated low-overhead thread that updates system, service, and docker telemetry."""
    psutil.cpu_percent(interval=None)
    
    # Static info cached once
    node_name = platform.node()
    os_info = platform.system() + " " + platform.release()
    kernel_info = platform.version()
    py_ver = platform.python_version()
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    
    while True:
        try:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            cpu_val = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            mem_pct = mem.percent
            mem_used_gb = round(mem.used / (1024**3), 2)
            mem_total_gb = round(mem.total / (1024**3), 2)

            uptime = datetime.datetime.now() - boot_time
            disk = psutil.disk_usage('/')

            sys_info = {
                "hostname": node_name,
                "os": os_info,
                "kernel": kernel_info,
                "python_version": py_ver,
                "cpu_usage": f"{cpu_val:.1f}%",
                "cpu_raw": cpu_val,
                "memory_usage": f"{mem_pct:.1f}%",
                "memory_raw": mem_pct,
                "mem_used_gb": mem_used_gb,
                "mem_total_gb": mem_total_gb,
                "disk_usage": f"{disk.percent}% ({disk.used // (2**30)}GB / {disk.total // (2**30)}GB)",
                "uptime": str(uptime).split('.')[0]
            }

            # Sample Services efficiently via batch systemctl
            svcs = load_services()
            current_svc_points = {}
            if svcs:
                if os.name == 'posix':
                    unit_names = [f"{s['name']}.service" for s in svcs]
                    service_props = {}
                    try:
                        res = subprocess.run(
                            ['systemctl', 'show', *unit_names, '-p', 'Id,ActiveState,MainPID,MemoryCurrent'],
                            capture_output=True, text=True, timeout=2
                        )
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

                    for s in svcs:
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
                        s['cpu_raw'] = 0.0
                        s['mem_raw'] = 0.0

                        if s['is_running']:
                            if mem_bytes > 0:
                                s['mem_raw'] = round(mem_bytes / (1024 * 1024), 1)
                                s['mem'] = f"{s['mem_raw']}MB"
                            if main_pid > 0 and psutil.pid_exists(main_pid):
                                try:
                                    proc = psutil.Process(main_pid)
                                    cpu_p = proc.cpu_percent(interval=None)
                                    for child in proc.children(recursive=True):
                                        try:
                                            cpu_p += child.cpu_percent(interval=None)
                                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                                            pass
                                    s['cpu_raw'] = round(cpu_p, 1)
                                    s['cpu'] = f"{s['cpu_raw']}%"
                                    if mem_bytes == 0:
                                        rss = proc.memory_info().rss
                                        for child in proc.children(recursive=True):
                                            try:
                                                rss += child.memory_info().rss
                                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                                pass
                                        s['mem_raw'] = round(rss / (1024 * 1024), 1)
                                        s['mem'] = f"{s['mem_raw']}MB"
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass

                        current_svc_points[s['name']] = {
                            "time": timestamp,
                            "cpu": s['cpu_raw'],
                            "mem": s['mem_raw']
                        }
                else:
                    for s in svcs:
                        s['is_running'] = False
                        s['cpu'] = "0.0%"
                        s['mem'] = "0MB"
                        s['cpu_raw'] = 0.0
                        s['mem_raw'] = 0.0
                        current_svc_points[s['name']] = {
                            "time": timestamp,
                            "cpu": 0.0,
                            "mem": 0.0
                        }

            # Sample Docker only if daemon is available
            current_cnt_points = {}
            if docker_manager.is_docker_available():
                docker_summary = docker_manager.get_docker_system_summary()
                if docker_summary.get('available') and docker_summary.get('containers'):
                    for c in docker_summary['containers']:
                        cpu_num = 0.0
                        mem_num = 0.0
                        try:
                            cpu_num = float(c['cpu'].replace('%', '').strip())
                        except:
                            pass
                        try:
                            mem_str = c['mem_usage'].split('/')[0].strip()
                            if 'GiB' in mem_str or 'GB' in mem_str:
                                mem_num = float(mem_str.replace('GiB','').replace('GB','').strip()) * 1024
                            elif 'MiB' in mem_str or 'MB' in mem_str:
                                mem_num = float(mem_str.replace('MiB','').replace('MB','').strip())
                            elif 'KiB' in mem_str or 'kB' in mem_str:
                                mem_num = float(mem_str.replace('KiB','').replace('kB','').strip()) / 1024
                        except:
                            pass
                        
                        c['cpu_raw'] = round(cpu_num, 1)
                        c['mem_raw'] = round(mem_num, 1)

                        current_cnt_points[c['id']] = {
                            "time": timestamp,
                            "cpu": round(cpu_num, 1),
                            "mem": round(mem_num, 1),
                            "name": c['name']
                        }
            else:
                docker_summary = {
                    'available': False,
                    'image_count': 0,
                    'container_count': 0,
                    'running_count': 0,
                    'stopped_count': 0,
                    'total_cpu': '0.0%',
                    'total_mem': '0MB'
                }

            # Record system point
            point = {
                "time": timestamp,
                "cpu": round(cpu_val, 1),
                "ram": round(mem_pct, 1),
                "docker_cpu": float(docker_summary.get('total_cpu', '0.0%').replace('%', '').strip()) if docker_summary.get('available') else 0.0
            }

            docker_apps_list = []
            if docker_summary.get('available'):
                docker_apps_list = docker_manager.get_docker_apps(containers=docker_summary.get('containers', []))

            with _lock:
                global cached_system_info, cached_services, cached_docker_summary, cached_docker_apps
                cached_system_info = sys_info
                cached_services = svcs
                cached_docker_summary = docker_summary
                cached_docker_apps = docker_apps_list
                system_history.append(point)

                # Append per-service history
                for s_name, p in current_svc_points.items():
                    if s_name not in service_history:
                        service_history[s_name] = deque(maxlen=HISTORY_MAX_POINTS)
                    service_history[s_name].append(p)

                # Append per-container history
                for c_id, p in current_cnt_points.items():
                    if c_id not in container_history:
                        container_history[c_id] = deque(maxlen=HISTORY_MAX_POINTS)
                    container_history[c_id].append(p)

        except Exception:
            pass

        time.sleep(2.0)

def start_monitor_thread():
    """Start the background metrics sampler daemon."""
    t = threading.Thread(target=_background_sampler, daemon=True)
    t.start()
