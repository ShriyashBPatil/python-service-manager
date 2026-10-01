import subprocess
import json
import os
import time

def run_docker_command(cmd_args, timeout=10):
    """Run a docker command and return (success, stdout, stderr)."""
    try:
        res = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return False, "", str(e)

_docker_available_cache = None
_docker_last_checked = 0.0

def is_docker_available():
    """Check if docker daemon is reachable with a 15-second cache to avoid subprocess overhead."""
    global _docker_available_cache, _docker_last_checked
    now = time.time()
    if _docker_available_cache is not None and (now - _docker_last_checked < 15.0):
        return _docker_available_cache
    success, _, _ = run_docker_command(['docker', 'info'], timeout=2)
    _docker_available_cache = success
    _docker_last_checked = now
    return success

def get_docker_stats_map():
    """Return a mapping of container name/id to live cpu, mem stats."""
    if not is_docker_available():
        return {}
    success, out, _ = run_docker_command(['docker', 'stats', '--no-stream', '--format', '{{json .}}'], timeout=3)
    if not success or not out:
        return {}
    stats = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            cid = item.get('ID', '')
            name = item.get('Name', '')
            data = {
                'cpu': item.get('CPUPerc', '0.0%'),
                'mem_usage': item.get('MemUsage', '0MB'),
                'mem_percent': item.get('MemPerc', '0.0%'),
                'net_io': item.get('NetIO', '0B / 0B'),
                'block_io': item.get('BlockIO', '0B / 0B'),
                'pids': item.get('PIDs', '0')
            }
            if cid:
                stats[cid] = data
            if name:
                stats[name] = data
        except Exception:
            continue
    return stats

def get_docker_images():
    """List all Docker images with metadata and usage state."""
    if not is_docker_available():
        return []

    # Get running/existing container images to know if an image is in use
    success, containers_out, _ = run_docker_command(['docker', 'ps', '-a', '--format', '{{.Image}}'], timeout=3)
    used_images = set(containers_out.splitlines()) if success and containers_out else set()

    success, out, _ = run_docker_command(['docker', 'images', '--format', '{{json .}}'], timeout=3)
    if not success or not out:
        return []

    images = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            repo = item.get('Repository', '<none>')
            tag = item.get('Tag', '<none>')
            image_id = item.get('ID', '')
            full_ref = f"{repo}:{tag}" if tag != '<none>' else repo

            in_use = (
                repo in used_images or
                full_ref in used_images or
                image_id in used_images or
                any(image_id.startswith(u) or u.startswith(image_id) for u in used_images)
            )

            images.append({
                'id': image_id,
                'repository': repo,
                'tag': tag,
                'size': item.get('Size', 'N/A'),
                'created_at': item.get('CreatedAt', ''),
                'created_since': item.get('CreatedSince', ''),
                'containers': item.get('Containers', '0'),
                'in_use': in_use or (item.get('Containers', '0') not in ('0', 'N/A', ''))
            })
        except Exception:
            continue

    return images

def get_docker_containers():
    """List all Docker containers with real-time stats."""
    if not is_docker_available():
        return []

    success, out, _ = run_docker_command(['docker', 'ps', '-a', '--format', '{{json .}}'], timeout=3)
    if not success or not out:
        return []

    stats_map = get_docker_stats_map()
    containers = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            cid = item.get('ID', '')
            cname = item.get('Names', '')
            stat = stats_map.get(cid) or stats_map.get(cname) or {
                'cpu': '0.0%',
                'mem_usage': '0MB',
                'mem_percent': '0.0%',
                'net_io': '-',
                'block_io': '-',
                'pids': '-'
            }

            containers.append({
                'id': cid,
                'name': cname,
                'image': item.get('Image', ''),
                'state': item.get('State', '').lower(),
                'status': item.get('Status', ''),
                'ports': item.get('Ports', ''),
                'created_since': item.get('RunningFor', ''),
                'cpu': stat['cpu'],
                'mem_usage': stat['mem_usage'],
                'mem_percent': stat['mem_percent'],
                'net_io': stat['net_io'],
                'block_io': stat['block_io'],
                'pids': stat['pids']
            })
        except Exception:
            continue

    return containers

def get_docker_system_summary():
    """Get aggregate Docker statistics."""
    if not is_docker_available():
        return {
            'available': False,
            'image_count': 0,
            'container_count': 0,
            'running_count': 0,
            'stopped_count': 0,
            'total_cpu': '0.0%',
            'total_mem': '0MB'
        }
    
    images = get_docker_images()
    containers = get_docker_containers()
    running = [c for c in containers if c['state'] == 'running']

    # Aggregate CPU & Mem
    total_cpu = 0.0
    for c in running:
        try:
            cpu_val = float(c['cpu'].replace('%', '').strip())
            total_cpu += cpu_val
        except:
            pass

    return {
        'available': True,
        'image_count': len(images),
        'container_count': len(containers),
        'running_count': len(running),
        'stopped_count': len(containers) - len(running),
        'total_cpu': f"{total_cpu:.1f}%",
        'images': images,
        'containers': containers
    }

def pull_docker_image(image_name):
    """Pull an image from registry."""
    if not image_name or not image_name.strip():
        return False, "Image name is required."
    success, stdout, stderr = run_docker_command(['docker', 'pull', image_name.strip()], timeout=60)
    if success:
        return True, f"Successfully pulled {image_name.strip()}"
    return False, stderr or stdout or "Failed to pull image."

def remove_docker_image(image_id, force=False):
    """Remove a docker image."""
    cmd = ['docker', 'rmi']
    if force:
        cmd.append('-f')
    cmd.append(image_id)
    success, stdout, stderr = run_docker_command(cmd)
    if success:
        return True, f"Removed image {image_id}"
    return False, stderr or stdout or "Failed to remove image."

def prune_docker_images():
    """Prune dangling/unused images."""
    success, stdout, stderr = run_docker_command(['docker', 'image', 'prune', '-f'])
    if success:
        return True, stdout or "Pruned unused Docker images."
    return False, stderr or "Failed to prune images."

def inspect_docker_image(image_id):
    """Inspect image details in JSON."""
    success, stdout, stderr = run_docker_command(['docker', 'inspect', image_id])
    if success:
        try:
            return json.loads(stdout)
        except Exception:
            return []
    return None

def inspect_docker_container(container_id):
    """Inspect container details in JSON."""
    success, stdout, stderr = run_docker_command(['docker', 'inspect', container_id])
    if success:
        try:
            return json.loads(stdout)
        except Exception:
            return []
    return None

def run_docker_container(image_name, container_name=None, ports=None, restart="unless-stopped", env_vars=None, volumes=None, detached=True):
    """Run a new container from image."""
    cmd = ['docker', 'run']
    if detached:
        cmd.append('-d')
    if container_name and container_name.strip():
        cmd.extend(['--name', container_name.strip()])
    if restart:
        cmd.extend(['--restart', restart])
    if ports and ports.strip():
        for p in ports.strip().split(','):
            p = p.strip()
            if p:
                cmd.extend(['-p', p])
    if env_vars and env_vars.strip():
        for line in env_vars.strip().splitlines():
            line = line.strip()
            if line and '=' in line:
                cmd.extend(['-e', line])
    if volumes and volumes.strip():
        for v in volumes.strip().split(','):
            v = v.strip()
            if v:
                cmd.extend(['-v', v])
    cmd.append(image_name.strip())

    success, stdout, stderr = run_docker_command(cmd, timeout=30)
    if success:
        return True, f"Container started successfully. ID: {stdout[:12]}"
    return False, stderr or stdout or "Failed to run container."

def container_action(container_id, action):
    """Start, stop, restart, or remove a container."""
    if action not in ('start', 'stop', 'restart', 'rm'):
        return False, "Invalid container action."
    cmd = ['docker', action, container_id]
    success, stdout, stderr = run_docker_command(cmd)
    if success:
        return True, f"Action '{action}' executed for container {container_id}."
    return False, stderr or stdout or f"Failed to execute {action}."

def get_docker_apps(containers=None):
    """Discover and group Docker applications/stacks (like Plane App, XAMPP, Jupyter, Portainer, etc.)
    including stopped apps so they remain visible and controllable until started again."""
    if not is_docker_available():
        return []

    if containers is None:
        containers = get_docker_containers()
    compose_projects = {}
    standalone_apps = {}

    standalone_map = {
        'jupyter': {'name': 'Jupyter Notebook', 'icon': 'bi-journal-code', 'type': 'Data & Python Notebook', 'port': '9874'},
        'portainer': {'name': 'Portainer CE', 'icon': 'bi-hdd-stack', 'type': 'Docker Environment Hub', 'port': '8555'},
        'n8n': {'name': 'n8n Automation', 'icon': 'bi-diagram-3', 'type': 'Workflow Automation', 'port': '5678'},
    }

    # Fetch labels for all containers to group compose projects accurately
    success, out, _ = run_docker_command(['docker', 'ps', '-a', '--format', '{{.ID}}\t{{.Names}}\t{{.Labels}}'], timeout=4)
    container_labels = {}
    if success and out:
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) >= 3:
                cid, cname, raw_labels = parts[0], parts[1], parts[2]
                labels = {}
                for item in raw_labels.split(','):
                    if '=' in item:
                        k, v = item.split('=', 1)
                        labels[k.strip()] = v.strip()
                container_labels[cid] = labels
                container_labels[cname] = labels

    # Known compose apps to keep visible even if stopped
    known_compose_dirs = [
        {
            'id': 'plane-app',
            'name': 'Plane Workspace App',
            'dir': '/opt/plane-selfhost/plane-app',
            'compose_file': '/opt/plane-selfhost/plane-app/docker-compose.yaml',
            'icon': 'bi-airplane-engines',
            'type': 'Project & Task Management',
            'web_port': '8777'
        },
        {
            'id': 'xampp-env',
            'name': 'XAMPP Web Stack',
            'dir': '/root/xampp-env',
            'compose_file': '/root/xampp-env/docker-compose.yml',
            'icon': 'bi-globe2',
            'type': 'Apache, PHP & MariaDB',
            'web_port': '8181'
        },
        {
            'id': 'filebrowser',
            'name': 'FileBrowser Cloud',
            'dir': '/opt/filebrowser',
            'compose_file': '/opt/filebrowser/docker-compose.yml',
            'icon': 'bi-folder2-open',
            'type': 'Web File Manager',
            'web_port': '8080'
        }
    ]

    for kc in known_compose_dirs:
        if os.path.exists(kc['dir']) or os.path.exists(kc['compose_file']):
            compose_projects[kc['id']] = {
                'id': kc['id'],
                'name': kc['name'],
                'icon': kc['icon'],
                'type': kc['type'],
                'dir': kc['dir'],
                'compose_file': kc['compose_file'],
                'web_port': kc['web_port'],
                'containers': [],
                'is_compose': True
            }

    # Group containers into compose projects or standalone apps
    for c in containers:
        cid = c['id']
        cname = c['name']
        labels = container_labels.get(cid) or container_labels.get(cname) or {}
        project = labels.get('com.docker.compose.project')
        
        if not project:
            if cname.startswith('plane-app-') or 'plane' in c['image']:
                project = 'plane-app'
            elif cname.startswith('xampp_') or 'xampp' in c['image']:
                project = 'xampp-env'

        if project:
            if project not in compose_projects:
                proj_name = project.replace('-', ' ').replace('_', ' ').title()
                compose_projects[project] = {
                    'id': project,
                    'name': proj_name,
                    'icon': 'bi-box-seam',
                    'type': 'Docker Compose Stack',
                    'dir': labels.get('com.docker.compose.project.working_dir', ''),
                    'compose_file': labels.get('com.docker.compose.project.config_files', ''),
                    'web_port': '',
                    'containers': [],
                    'is_compose': True
                }
            compose_projects[project]['containers'].append(c)
        else:
            matched_key = None
            for k, info in standalone_map.items():
                if k in cname.lower() or k in c['image'].lower():
                    matched_key = k
                    break
            
            app_id = cname
            app_name = standalone_map[matched_key]['name'] if matched_key else cname
            app_icon = standalone_map[matched_key]['icon'] if matched_key else 'bi-box'
            app_type = standalone_map[matched_key]['type'] if matched_key else 'Container App'
            app_port = standalone_map[matched_key]['port'] if matched_key else ''

            standalone_apps[app_id] = {
                'id': app_id,
                'name': app_name,
                'icon': app_icon,
                'type': app_type,
                'dir': '',
                'compose_file': '',
                'web_port': app_port,
                'containers': [c],
                'is_compose': False
            }

    all_apps = []
    
    for pid, pdata in compose_projects.items():
        conts = pdata['containers']
        running_cnt = len([c for c in conts if c['state'] == 'running'])
        total_cnt = len(conts)
        
        if total_cnt == 0:
            status = 'stopped'
            status_text = 'Stopped (Idle)'
        elif running_cnt == total_cnt:
            status = 'running'
            status_text = 'All Running'
        elif running_cnt > 0:
            status = 'partial'
            status_text = f'{running_cnt}/{total_cnt} Running'
        else:
            status = 'stopped'
            status_text = 'Stopped'

        tot_cpu = 0.0
        for c in conts:
            try:
                tot_cpu += float(c['cpu'].replace('%', '').strip())
            except:
                pass

        pdata['status'] = status
        pdata['status_text'] = status_text
        pdata['running_count'] = running_cnt
        pdata['total_count'] = total_cnt
        pdata['total_cpu'] = f"{tot_cpu:.1f}%"
        all_apps.append(pdata)

    for aid, adata in standalone_apps.items():
        c = adata['containers'][0]
        adata['status'] = c['state']
        adata['status_text'] = 'Running' if c['state'] == 'running' else 'Stopped'
        adata['running_count'] = 1 if c['state'] == 'running' else 0
        adata['total_count'] = 1
        adata['total_cpu'] = c['cpu']
        all_apps.append(adata)

    def sort_key(app):
        if app['id'] == 'plane-app':
            return 0
        if app['is_compose']:
            return 1
        return 2

    all_apps.sort(key=sort_key)
    return all_apps

def stack_action(stack_id, action):
    """Start, stop, or restart an entire Docker application stack."""
    if action not in ('start', 'stop', 'restart', 'up', 'down'):
        return False, "Invalid stack action."
    
    apps = get_docker_apps()
    target_app = next((a for a in apps if a['id'] == stack_id), None)
    
    if not target_app:
        return container_action(stack_id, action)

    compose_file = target_app.get('compose_file')
    compose_dir = target_app.get('dir')

    if compose_file and os.path.exists(compose_file):
        cmd = ['docker', 'compose', '-f', compose_file]
        if action in ('start', 'up'):
            cmd.extend(['up', '-d'])
        elif action == 'stop':
            cmd.extend(['stop'])
        elif action == 'restart':
            cmd.extend(['restart'])
        elif action == 'down':
            cmd.extend(['down'])
        
        success, stdout, stderr = run_docker_command(cmd, timeout=60)
        if success:
            return True, f"App '{target_app['name']}' {action} completed successfully."

    containers = target_app.get('containers', [])
    if not containers:
        if compose_dir and os.path.exists(compose_dir):
            cmd = ['docker', 'compose', '--project-directory', compose_dir, 'up', '-d']
            success, stdout, stderr = run_docker_command(cmd, timeout=60)
            if success:
                return True, f"App '{target_app['name']}' started via compose."
        return False, f"No containers found for '{stack_id}'."

    errors = []
    for c in containers:
        cid = c['id']
        c_action = 'start' if action in ('start', 'up') else ('stop' if action == 'stop' else 'restart')
        success, msg = container_action(cid, c_action)
        if not success:
            errors.append(f"{c['name']}: {msg}")

    if errors:
        return False, "; ".join(errors)
    return True, f"App '{target_app['name']}' {action}ed successfully."

