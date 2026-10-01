from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_socketio import SocketIO, emit
import os
import paramiko
import threading
import subprocess
from config import load_settings, save_settings
from utils import get_system_info, check_port, browse_directory
from systemd import start_service, stop_service, restart_service, enable_service, disable_service, get_logs, scan_systemd_services, parse_systemd_file
from service_manager import get_service_details, create_service, update_service, delete_service, load_services, save_services
import docker_manager
import firewall_manager
from monitor import start_monitor_thread, get_live_system_info, get_cached_services, get_cached_docker, get_cached_docker_apps, get_metrics_history

app = Flask(__name__)
app.secret_key = "super_secret_service_manager_key"
socketio = SocketIO(app, cors_allowed_origins="*")

# Start daemon sampler
start_monitor_thread()

# Store SSH sessions and channels per websocket session id
ssh_sessions = {}

@app.context_processor
def inject_settings():
    is_admin = bool(session.get('logged_in'))
    return dict(
        settings=load_settings(),
        sys_info=get_live_system_info(),
        is_admin=is_admin,
        is_guest=not is_admin
    )

@app.before_request
def require_login():
    # Read-only public routes accessible in guest mode
    guest_allowed = [
        'dashboard',
        'api_telemetry',
        'view_logs',
        'api_logs',
        'docker_inspect_image',
        'docker_inspect_container',
        'port_checker',
        'login',
        'guest_login',
        'logout',
        'static'
    ]
    
    endpoint = request.endpoint
    if endpoint and endpoint not in guest_allowed:
        # Check if user is authenticated admin
        if not session.get('logged_in'):
            if request.is_json or request.path.startswith('/api/') or request.method == 'POST':
                return jsonify({"success": False, "message": "Admin authorization required (Guest mode is read-only)."}), 403
            flash("Admin access required for this action.", "warning")
            return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        settings = load_settings()
        correct_password = settings.get('password', 'admin')
        if not correct_password:
            correct_password = 'admin'
            
        if request.form.get('password') == correct_password:
            session['logged_in'] = True
            session.permanent = True
            flash("Welcome! Logged in as Administrator.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid password.", "danger")
    return render_template('login.html')

@app.route('/guest')
def guest_login():
    session.pop('logged_in', None)
    flash("Viewing dashboard in Guest (Read-Only) mode.", "info")
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    services = get_cached_services()
    if not services:
        services = get_service_details()
    docker_summary = get_cached_docker()
    if not docker_summary:
        docker_summary = docker_manager.get_docker_system_summary()
    docker_apps = get_cached_docker_apps()
    if not docker_apps:
        docker_apps = docker_manager.get_docker_apps(containers=docker_summary.get('containers', []))
    aic_cloud = firewall_manager.get_aic_cloud_overview()
    return render_template('dashboard.html', services=services, docker=docker_summary, docker_apps=docker_apps, aic_cloud=aic_cloud)

@app.route('/api/telemetry')
def api_telemetry():
    return jsonify({
        "sys_info": get_live_system_info(),
        "history": get_metrics_history(),
        "services": get_cached_services(),
        "docker": get_cached_docker(),
        "docker_apps": get_cached_docker_apps(),
        "aic_cloud": firewall_manager.get_aic_cloud_overview()
    })

@app.route('/docker/stack/<action>/<stack_id>', methods=['POST'])
def docker_stack_action(action, stack_id):
    success, msg = docker_manager.stack_action(stack_id, action)
    return jsonify({"success": success, "message": msg})



@app.route('/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        data = {
            'name': request.form.get('name'),
            'description': request.form.get('description'),
            'python_file': request.form.get('python_file'),
            'working_dir': request.form.get('working_dir'),
            'venv': request.form.get('venv'),
            'user': request.form.get('user'),
            'restart': request.form.get('restart'),
            'env_vars': request.form.get('env_vars'),
            'autostart': 'autostart' in request.form
        }
        success, msg = create_service(data)
        if success:
            flash(msg, 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(msg, 'danger')
            return render_template('create.html', defaults=data)
            
    settings = load_settings()
    defaults = {
        'user': settings.get('default_user', 'root'),
        'restart': settings.get('default_restart_policy', 'always'),
        'working_dir': settings.get('default_working_dir', '/root')
    }
    return render_template('create.html', defaults=defaults)

@app.route('/edit/<name>', methods=['GET', 'POST'])
def edit(name):
    services = load_services()
    service_data = next((s for s in services if s['name'] == name), None)
    
    if not service_data:
        flash("Service not found.", "danger")
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        service_data['description'] = request.form.get('description')
        service_data['python_file'] = request.form.get('python_file')
        service_data['working_dir'] = request.form.get('working_dir')
        service_data['venv'] = request.form.get('venv')
        service_data['user'] = request.form.get('user')
        service_data['restart'] = request.form.get('restart')
        service_data['env_vars'] = request.form.get('env_vars')
        
        success, msg = update_service(name, service_data)
        if success:
            flash(msg, 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(msg, 'danger')
            
    return render_template('edit.html', service=service_data)

@app.route('/action/<action>/<name>', methods=['POST'])
def service_action(action, name):
    success, msg = False, "Unknown action"
    if action == 'start':
        success, msg = start_service(name)
    elif action == 'stop':
        success, msg = stop_service(name)
    elif action == 'restart':
        success, msg = restart_service(name)
    elif action == 'enable':
        success, msg = enable_service(name)
    elif action == 'disable':
        success, msg = disable_service(name)
    elif action == 'delete':
        success, msg = delete_service(name)
        
    return jsonify({"success": success, "message": msg})

@app.route('/logs/<name>')
def view_logs(name):
    return render_template('logs.html', name=name)

@app.route('/api/logs/<name>')
def api_logs(name):
    lines = request.args.get('lines', 100)
    log_data = get_logs(name, lines)
    return jsonify({"logs": log_data})

@app.route('/port_checker', methods=['GET', 'POST'])
def port_checker():
    result = None
    port = None
    if request.method == 'POST':
        port = request.form.get('port')
        if port and port.isdigit():
            success, msg = check_port(port)
            result = {"success": success, "msg": msg}
        else:
            result = {"success": False, "msg": "Invalid port number"}
    return render_template('port_checker.html', result=result, port=port)

@app.route('/settings', methods=['GET', 'POST'])
def view_settings():
    if request.method == 'POST':
        new_settings = {
            "default_user": request.form.get('default_user'),
            "default_restart_policy": request.form.get('default_restart_policy'),
            "default_working_dir": request.form.get('default_working_dir'),
            "theme": request.form.get('theme'),
            "password": request.form.get('password') or 'admin',
            "aic_api_key": request.form.get('aic_api_key', '').strip()
        }
        save_settings(new_settings)
        flash("Settings saved successfully.", "success")
        return redirect(url_for('view_settings'))
    aic_cloud = firewall_manager.get_aic_cloud_overview()
    return render_template('settings.html', aic_cloud=aic_cloud)

@app.route('/api/aic/overview')
def api_aic_overview():
    return jsonify(firewall_manager.get_aic_cloud_overview())

@app.route('/terminal')
def terminal():
    return render_template('terminal.html')

# --- WebSocket Terminal Logic ---

def ssh_reader(channel, sid):
    """Continuously read from the SSH channel and send to the WebSocket client."""
    try:
        while True:
            if channel.recv_ready():
                data = channel.recv(1024).decode('utf-8', errors='replace')
                socketio.emit('pty-output', {'output': data}, to=sid)
            else:
                socketio.sleep(0.01)
                
            if channel.exit_status_ready():
                socketio.emit('pty-output', {'output': '\r\n--- Connection Closed ---\r\n'}, to=sid)
                break
    except Exception as e:
        socketio.emit('pty-output', {'output': f'\r\n--- Error reading SSH: {e} ---\r\n'}, to=sid)

@socketio.on('ssh-connect')
def handle_ssh_connect(data):
    sid = request.sid
    hostname = data.get('hostname', '127.0.0.1')
    try:
        port = int(data.get('port', 22))
    except ValueError:
        port = 22
    username = data.get('username', 'root')
    password = data.get('password')
    
    if not password:
        emit('pty-output', {'output': '\r\nPassword is required.\r\n'})
        return
        
    try:
        emit('pty-output', {'output': f'\r\nConnecting to {username}@{hostname}:{port}...\r\n'})
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            timeout=10
        )
        channel = client.invoke_shell()
        channel.setblocking(0)
        
        ssh_sessions[sid] = {'client': client, 'channel': channel}
        
        # Start background reader task
        socketio.start_background_task(ssh_reader, channel, sid)
        
    except Exception as e:
        emit('pty-output', {'output': f'\r\nConnection Failed: {e}\r\n'})

@socketio.on('pty-input')
def handle_pty_input(data):
    sid = request.sid
    if sid in ssh_sessions:
        channel = ssh_sessions[sid]['channel']
        if channel.send_ready():
            channel.send(data['input'])

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in ssh_sessions:
        try:
            ssh_sessions[sid]['client'].close()
        except:
            pass
        del ssh_sessions[sid]

@app.route('/api/browse', methods=['POST'])
def api_browse():
    path = request.json.get('path', '')
    data = browse_directory(path)
    return jsonify(data)

@app.route('/import', methods=['GET', 'POST'])
def import_service():
    if request.method == 'POST':
        service_name = request.form.get('service_name')
        if not service_name:
            flash("Service name is required.", "danger")
            return redirect(url_for('import_service'))
            
        config = parse_systemd_file(service_name)
        if not config:
            flash(f"Could not read or parse {service_name}.service.", "danger")
            return redirect(url_for('import_service'))
            
        # Try to guess python_file and venv from exec_start
        python_file = ''
        venv = ''
        exec_parts = config['exec_start'].split()
        if len(exec_parts) >= 2:
            python_file = exec_parts[-1]
            if '/bin/python' in exec_parts[0] or '/bin/gunicorn' in exec_parts[0]:
                venv = exec_parts[0].rsplit('/bin/', 1)[0]
        else:
            python_file = config['exec_start']
            
        # Default autostart based on what it is
        new_service = {
            'name': config['name'],
            'description': config['description'] or 'Imported Service',
            'python_file': python_file,
            'working_dir': config['working_dir'],
            'venv': venv,
            'user': config['user'] or 'root',
            'restart': config['restart'] or 'always',
            'env_vars': config['env_vars'],
            'autostart': True
        }
        
        # Add to services.json if not exists
        services = load_services()
        if any(s['name'] == new_service['name'] for s in services):
            flash("Service is already managed by the manager.", "info")
        else:
            services.append(new_service)
            save_services(services)
            flash(f"Successfully imported {service_name}.service!", "success")
            
        return redirect(url_for('dashboard'))

    # GET request
    system_services = scan_systemd_services()
    # Filter out ones already managed
    managed = [s['name'] for s in load_services()]
    unmanaged = [s for s in system_services if s['name'] not in managed]
    
    return render_template('import.html', system_services=unmanaged)

# --- Docker Management Routes ---

@app.route('/docker')
def docker_dashboard():
    available = docker_manager.is_docker_available()
    images = docker_manager.get_docker_images() if available else []
    containers = docker_manager.get_docker_containers() if available else []
    apps = docker_manager.get_docker_apps() if available else []
    return render_template('docker.html', available=available, images=images, containers=containers, apps=apps)

@app.route('/docker/pull', methods=['POST'])
def docker_pull():
    image_name = request.form.get('image_name', '').strip()
    if not image_name:
        flash("Image name cannot be empty.", "danger")
    else:
        success, msg = docker_manager.pull_docker_image(image_name)
        flash(msg, "success" if success else "danger")
    return redirect(url_for('docker_dashboard'))

@app.route('/docker/remove', methods=['POST'])
def docker_remove():
    image_id = request.form.get('image_id', '').strip()
    force = request.form.get('force') == '1'
    if not image_id:
        flash("Image ID required.", "danger")
    else:
        success, msg = docker_manager.remove_docker_image(image_id, force=force)
        flash(msg, "success" if success else "danger")
    return redirect(url_for('docker_dashboard'))

@app.route('/docker/prune', methods=['POST'])
def docker_prune():
    success, msg = docker_manager.prune_docker_images()
    flash(msg, "success" if success else "danger")
    return redirect(url_for('docker_dashboard'))

@app.route('/docker/run', methods=['POST'])
def docker_run():
    image_name = request.form.get('image_name', '').strip()
    container_name = request.form.get('container_name', '').strip()
    ports = request.form.get('ports', '').strip()
    restart = request.form.get('restart', 'unless-stopped')
    if not image_name:
        flash("Image name is required to run a container.", "danger")
    else:
        success, msg = docker_manager.run_docker_container(image_name, container_name, ports, restart)
        flash(msg, "success" if success else "danger")
    return redirect(url_for('docker_dashboard'))

@app.route('/docker/container/<action>/<container_id>', methods=['POST'])
def docker_container_action(action, container_id):
    success, msg = docker_manager.container_action(container_id, action)
    return jsonify({"success": success, "message": msg})

@app.route('/api/docker/inspect/image/<image_id>')
def docker_inspect_image(image_id):
    data = docker_manager.inspect_docker_image(image_id)
    return jsonify({"inspect": data})

@app.route('/api/docker/inspect/container/<container_id>')
def docker_inspect_container(container_id):
    data = docker_manager.inspect_docker_container(container_id)
    return jsonify({"inspect": data})

# --- Server Control Routes (Start/Stop/Reboot) ---

@app.route('/api/server/power/<action>', methods=['POST'])
def server_power_action(action):
    if action == 'reboot' or action == 'restart':
        success, msg = firewall_manager.restart_server()
        return jsonify({"success": success, "message": msg})
    elif action == 'poweroff' or action == 'shutdown' or action == 'stop':
        success, msg = firewall_manager.shutdown_server()
        return jsonify({"success": success, "message": msg})
    else:
        return jsonify({"success": False, "message": f"Unknown server action: {action}"}), 400

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)



