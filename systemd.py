import subprocess
import os

def run_command(cmd_list, check=True):
    """Run a subprocess command and return (success, output)."""
    if os.name != 'posix':
        return False, f"Command not supported on Windows: {' '.join(cmd_list)}"
    
    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True)
        if check and result.returncode != 0:
            return False, result.stderr.strip()
        return True, result.stdout.strip()
    except Exception as e:
        return False, str(e)

def daemon_reload():
    return run_command(["systemctl", "daemon-reload"])

def enable_service(service_name):
    return run_command(["systemctl", "enable", f"{service_name}.service"])

def disable_service(service_name):
    return run_command(["systemctl", "disable", f"{service_name}.service"])

def start_service(service_name):
    return run_command(["systemctl", "start", f"{service_name}.service"])

def stop_service(service_name):
    return run_command(["systemctl", "stop", f"{service_name}.service"])

def restart_service(service_name):
    return run_command(["systemctl", "restart", f"{service_name}.service"])

def check_service_status(service_name):
    # Use check=False so a non-zero exit code (e.g. 3 for inactive) doesn't raise an error
    _, out = run_command(["systemctl", "is-active", f"{service_name}.service"], check=False)
    return out.strip() == "active"


def get_logs(service_name, lines=100):
    if os.name != 'posix':
        return "Logs not available on Windows."
    
    try:
        cmd = [
            "journalctl",
            "-u", f"{service_name}.service",
            "-n", str(lines),
            "--no-pager",
            "--output=short-precise"   # includes timestamps + full stdout/stderr from the process
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout
        if result.stderr:
            output += "\n[journalctl stderr]: " + result.stderr
        return output if output.strip() else "No logs found."
    except Exception as e:
        return str(e)

def write_systemd_file(service_name, content):
    """Write the .service file to /etc/systemd/system/."""
    if os.name != 'posix':
        return False, "Cannot write systemd file on Windows."
    
    path = f"/etc/systemd/system/{service_name}.service"
    try:
        with open(path, "w") as f:
            f.write(content)
        return True, f"Written {path}"
    except Exception as e:
        return False, str(e)

def delete_systemd_file(service_name):
    if os.name != 'posix':
        return False, "Cannot delete systemd file on Windows."
        
    path = f"/etc/systemd/system/{service_name}.service"
    try:
        if os.path.exists(path):
            os.remove(path)
        return True, f"Deleted {path}"
    except Exception as e:
        return False, str(e)

def parse_systemd_file(service_name):
    """Reads a .service file and parses its basic configuration."""
    if os.name != 'posix':
        return None
    path = f"/etc/systemd/system/{service_name}.service"
    if not os.path.exists(path):
        return None
        
    config = {
        'name': service_name,
        'description': '',
        'user': 'root',
        'working_dir': '',
        'exec_start': '',
        'restart': 'always',
        'env_vars': ''
    }
    
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
            
        envs = []
        for line in lines:
            line = line.strip()
            if line.startswith('Description='):
                config['description'] = line.split('=', 1)[1]
            elif line.startswith('User='):
                config['user'] = line.split('=', 1)[1]
            elif line.startswith('WorkingDirectory='):
                config['working_dir'] = line.split('=', 1)[1]
            elif line.startswith('ExecStart='):
                config['exec_start'] = line.split('=', 1)[1]
            elif line.startswith('Restart='):
                config['restart'] = line.split('=', 1)[1]
            elif line.startswith('Environment='):
                env_val = line.split('=', 1)[1].strip('"\'')
                envs.append(env_val)
                
        config['env_vars'] = '\n'.join(envs)
        return config
    except:
        return None

def scan_systemd_services():
    """Scans /etc/systemd/system for python-like services."""
    if os.name != 'posix':
        return []
        
    services = []
    directory = "/etc/systemd/system/"
    if not os.path.exists(directory):
        return []
        
    for filename in os.listdir(directory):
        if filename.endswith(".service"):
            svc_name = filename[:-8]
            config = parse_systemd_file(svc_name)
            if config and config['exec_start'] and ('python' in config['exec_start'] or 'gunicorn' in config['exec_start'] or 'uvicorn' in config['exec_start'] or 'flask' in config['exec_start']):
                services.append(config)
                
    return sorted(services, key=lambda x: x['name'])
