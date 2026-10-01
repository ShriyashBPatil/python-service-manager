import os
import glob
import psutil
import platform
import subprocess
import datetime

def get_system_info():
    """Retrieve system information using psutil and platform."""
    # Uptime
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.datetime.now() - boot_time
    # Disk usage
    disk = psutil.disk_usage('/')
    disk_usage = f"{disk.percent}% ({disk.used // (2**30)}GB / {disk.total // (2**30)}GB)"
    
    cpu_pct = psutil.cpu_percent(interval=0.1)
    
    return {
        "hostname": platform.node(),
        "os": platform.system() + " " + platform.release(),
        "kernel": platform.version(),
        "python_version": platform.python_version(),
        "cpu_usage": f"{cpu_pct:.1f}%",
        "memory_usage": f"{psutil.virtual_memory().percent}%",
        "disk_usage": disk_usage,
        "uptime": str(uptime).split('.')[0]
    }


def check_port(port):
    """Check if a port is in use, using ss on Linux or psutil on Windows."""
    port = str(port)
    if os.name == 'posix':
        try:
            # Using ss -tulpn as requested
            result = subprocess.run(['ss', '-tulpn'], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if f":{port} " in line:
                    return False, f"Already in use: {line.strip()}"
            return True, "Available"
        except Exception as e:
            return False, f"Error checking port: {str(e)}"
    else:
        # Fallback for Windows
        for conn in psutil.net_connections():
            if conn.laddr.port == int(port):
                return False, f"Already in use by PID {conn.pid}"
        return True, "Available"

def browse_directory(path):
    """Simple file browser logic returning directories and files."""
    if not path or not os.path.exists(path):
        # Default to root or current directory
        path = "/" if os.name == 'posix' else "C:\\"
        
    try:
        items = os.listdir(path)
    except PermissionError:
        return {"current_path": path, "parent": os.path.dirname(path), "directories": [], "files": [], "error": "Permission Denied"}
    
    directories = []
    files = []
    
    for item in items:
        full_path = os.path.join(path, item)
        try:
            if os.path.isdir(full_path):
                directories.append(item)
            else:
                files.append(item)
        except:
            pass # ignore unreadable files
            
    directories.sort()
    files.sort()
    
    return {
        "current_path": path,
        "parent": os.path.dirname(path) if path not in ("/", "C:\\") else path,
        "directories": directories,
        "files": files,
        "error": None
    }
