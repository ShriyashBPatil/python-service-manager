import subprocess
import os
import re

def run_cmd(cmd_list, check=True):
    """Run a subprocess command and return (success, output)."""
    if os.name != 'posix':
        return False, f"Command not supported on non-posix OS: {' '.join(cmd_list)}"
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True)
        if check and res.returncode != 0:
            return False, res.stderr.strip() or res.stdout.strip()
        return True, (res.stdout.strip() if res.stdout else res.stderr.strip())
    except Exception as e:
        return False, str(e)

# ----------------- Server Power Operations -----------------

def restart_server():
    """Trigger a system reboot."""
    success, out = run_cmd(["systemctl", "reboot"])
    if not success:
        # Fallback to reboot command
        success, out = run_cmd(["reboot"])
    return success, "Server reboot command issued." if success else f"Reboot failed: {out}"

def shutdown_server():
    """Trigger a system poweroff/halt."""
    success, out = run_cmd(["systemctl", "poweroff"])
    if not success:
        success, out = run_cmd(["poweroff"])
    return success, "Server shutdown command issued." if success else f"Shutdown failed: {out}"


# ----------------- Firewall Management (iptables & ufw) -----------------

def get_firewall_status():
    """
    Returns firewall system status and parsed rules.
    """
    # Check if ufw is installed and active
    ufw_installed, _ = run_cmd(["which", "ufw"], check=False)
    backend = "iptables"
    ufw_status_str = "inactive"
    
    if ufw_installed:
        _, ufw_out = run_cmd(["ufw", "status"], check=False)
        if "Status: active" in ufw_out:
            backend = "ufw"
            ufw_status_str = "active"
        else:
            ufw_status_str = "inactive"

    PROTO_MAP = {
        "6": "TCP",
        "17": "UDP",
        "1": "ICMP",
        "0": "ALL",
        "TCP": "TCP",
        "UDP": "UDP",
        "ICMP": "ICMP",
        "ALL": "ALL"
    }

    rules = []
    # Read filter table with line numbers
    success, out = run_cmd(["iptables", "-L", "INPUT", "-n", "--line-numbers", "-v"], check=False)
    if success and out:
        lines = out.strip().split("\n")
        # Header is usually first 2 lines
        for line in lines[2:]:
            line = line.strip()
            if not line:
                continue
            parts = re.split(r'\s+', line)
            if len(parts) >= 6 and parts[0].isdigit():
                num = parts[0]
                pkts = parts[1]
                bytes_cnt = parts[2]
                target = parts[3]
                prot_raw = parts[4].upper()
                prot = PROTO_MAP.get(prot_raw, prot_raw)
                opt = parts[5]
                in_if = parts[6] if len(parts) > 6 else "*"
                out_if = parts[7] if len(parts) > 7 else "*"
                source = parts[8] if len(parts) > 8 else "0.0.0.0/0"
                dest = parts[9] if len(parts) > 9 else "0.0.0.0/0"
                extra = " ".join(parts[10:]) if len(parts) > 10 else ""
                
                # Extract comment if present
                comment_match = re.search(r'/\*\s*(.*?)\s*\*/', extra)
                comment_str = comment_match.group(1) if comment_match else ""

                # Try to extract dport
                port_match = re.search(r'dpt:(\d+(?::\d+)?)', extra) or re.search(r'dports?\s+([\d,:]+)', extra)
                port = port_match.group(1) if port_match else "-"
                
                rules.append({
                    "num": int(num),
                    "target": target,
                    "prot": prot,
                    "source": source,
                    "destination": dest,
                    "port": port,
                    "comment": comment_str,
                    "extra": extra,
                    "packets": pkts,
                    "bytes": bytes_cnt,
                    "chain": "INPUT"
                })

    # Collect active listening ports on host
    listening_ports = []
    seen_ports = set()
    s_ok, s_out = run_cmd(["ss", "-tulpn"], check=False)
    if s_ok and s_out:
        for line in s_out.splitlines()[1:]:
            parts = re.split(r'\s+', line.strip())
            if len(parts) >= 5:
                netid = parts[0].upper()
                local = parts[4]
                proc_info = ' '.join(parts[6:]) if len(parts) > 6 else ''
                p_match = re.search(r':(\d+)$', local)
                if p_match:
                    port_num = p_match.group(1)
                    key = (netid, port_num)
                    if key in seen_ports:
                        continue
                    seen_ports.add(key)
                    proc_match = re.search(r'users:\(\(\"([^\"]+)\"', proc_info)
                    proc_name = proc_match.group(1) if proc_match else '-'
                    
                    # Friendlier service name mapping
                    friendly_name = proc_name
                    if port_num == "8000":
                        friendly_name = "Python Service Manager"
                    elif port_num == "3333":
                        friendly_name = "MailServer"
                    elif port_num == "6767":
                        friendly_name = "Office Broadcast Server"
                    elif port_num == "6969":
                        friendly_name = "Binge-Together Service"
                    elif port_num == "8899":
                        friendly_name = "Tomcat 10"
                    elif port_num == "3306":
                        friendly_name = "MariaDB Database"
                    elif port_num == "22":
                        friendly_name = "OpenSSH Server"
                    elif proc_name == "docker-proxy":
                        friendly_name = f"Docker Proxy ({port_num})"

                    listening_ports.append({
                        "port": port_num,
                        "proto": netid,
                        "process": proc_name,
                        "service_name": friendly_name,
                        "address": local
                    })

    # Sort ports numerically
    listening_ports.sort(key=lambda x: int(x["port"]) if x["port"].isdigit() else 999999)

    # Get default policy for INPUT chain
    default_policy = "ACCEPT"
    _, policy_out = run_cmd(["iptables", "-S", "INPUT"], check=False)
    if policy_out:
        p_match = re.search(r'-P\s+INPUT\s+(\w+)', policy_out)
        if p_match:
            default_policy = p_match.group(1)

    return {
        "backend": backend,
        "ufw_installed": bool(ufw_installed),
        "ufw_status": ufw_status_str,
        "default_policy": default_policy,
        "rules_count": len(rules),
        "rules": rules,
        "listening_ports": listening_ports
    }

def add_firewall_rule(chain="INPUT", action="ACCEPT", protocol="tcp", port=None, source=None, comment=None):
    """
    Add a new firewall rule to iptables.
    action: ACCEPT, DROP, REJECT
    protocol: tcp, udp, icmp, all
    port: integer or string (e.g. 80, 443, 8000:9000)
    source: IP/CIDR (e.g. 192.168.1.100, 10.0.0.0/24)
    """
    cmd = ["iptables", "-I", chain, "1"] # insert at top
    
    if source and source.strip() and source.strip() != "0.0.0.0/0" and source.strip() != "any":
        cmd.extend(["-s", source.strip()])
        
    if protocol and protocol.lower() != "all":
        cmd.extend(["-p", protocol.lower()])
        if port and str(port).strip() and protocol.lower() in ["tcp", "udp"]:
            cmd.extend(["--dport", str(port).strip().replace(" ", "")])
            
    if comment and comment.strip():
        # Clean comment string
        clean_comment = re.sub(r'[^a-zA-Z0-9_\-\. ]', '', comment.strip())[:64]
        cmd.extend(["-m", "comment", "--comment", clean_comment])
        
    cmd.extend(["-j", action.upper()])
    
    success, out = run_cmd(cmd)
    if success:
        return True, f"Firewall rule added successfully: {action.upper()} {protocol.upper()}{' port ' + str(port) if port else ''}"
    return False, f"Failed to add rule: {out}"

def delete_firewall_rule(chain="INPUT", rule_num=None, protocol=None, port=None, action="ACCEPT", source=None):
    """
    Delete a firewall rule either by rule number in chain or by match specification.
    """
    if rule_num is not None:
        try:
            num = int(rule_num)
            cmd = ["iptables", "-D", chain, str(num)]
            success, out = run_cmd(cmd)
            if success:
                return True, f"Rule #{num} deleted from {chain} chain."
            return False, f"Failed to delete rule #{num}: {out}"
        except ValueError:
            pass

    # Fallback to deleting by spec
    cmd = ["iptables", "-D", chain]
    if source and source.strip() and source.strip() != "0.0.0.0/0":
        cmd.extend(["-s", source.strip()])
    if protocol and protocol.lower() != "all":
        cmd.extend(["-p", protocol.lower()])
        if port and str(port).strip() and protocol.lower() in ["tcp", "udp"]:
            cmd.extend(["--dport", str(port).strip()])
    cmd.extend(["-j", action.upper()])
    
    success, out = run_cmd(cmd)
    if success:
        return True, "Firewall rule deleted successfully."
    return False, f"Failed to delete rule: {out}"

def set_firewall_default_policy(chain="INPUT", policy="ACCEPT"):
    """Set default policy (ACCEPT / DROP) for a chain."""
    if policy.upper() not in ["ACCEPT", "DROP"]:
        return False, "Invalid policy. Must be ACCEPT or DROP."
    cmd = ["iptables", "-P", chain, policy.upper()]
    success, out = run_cmd(cmd)
    if success:
        return True, f"Default policy for {chain} set to {policy.upper()}."
    return False, f"Failed to change policy: {out}"

def flush_custom_firewall_rules(chain="INPUT"):
    """Flushes rules in the specified chain."""
    cmd = ["iptables", "-F", chain]
    success, out = run_cmd(cmd)
    if success:
        return True, f"Flushed all rules in {chain} chain."
    return False, f"Failed to flush rules: {out}"


# ----------------- AIC Cloud API Integration -----------------

import urllib.request
import json

AIC_API_BASE_URL = "https://api.aiccloud.in"
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_aic_api_key():
    """Retrieve AIC API key from settings.json or environment."""
    from config import load_settings
    settings = load_settings()
    key = settings.get("aic_api_key", "").strip()
    if not key:
        key = os.environ.get("AIC_API_KEY", "aic_c901f455f38f54d264f524500f7bada4779c112cdcfd30f1").strip()
    return key

def aic_api_request(endpoint, method="GET", data=None, api_key=None):
    """Execute authenticated REST request to AIC Cloud API."""
    key = api_key or get_aic_api_key()
    if not key:
        return False, "AIC API key not configured."
    
    url = f"{AIC_API_BASE_URL}{endpoint}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json"
    }
    
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
        
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            try:
                res_json = json.loads(content)
                return True, res_json
            except json.JSONDecodeError:
                return True, content
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_msg)
            return False, err_json.get("error", err_msg)
        except Exception:
            return False, f"HTTP {e.code}: {err_msg or e.reason}"
    except Exception as e:
        return False, str(e)

def get_aic_cloud_overview(api_key=None):
    """Fetch AIC Cloud VPS instances, wallet, and metadata."""
    key = api_key or get_aic_api_key()
    if not key:
        return {
            "configured": False,
            "connected": False,
            "instances": [],
            "wallet": None,
            "error": "No AIC API Key configured"
        }
        
    vps_ok, vps_data = aic_api_request("/api/v1/vps", api_key=key)
    wallet_ok, wallet_data = aic_api_request("/api/v1/billing/wallet", api_key=key)
    
    instances = []
    if vps_ok and isinstance(vps_data, dict):
        instances = vps_data.get("instances", vps_data.get("vps", []))
    elif vps_ok and isinstance(vps_data, list):
        instances = vps_data
        
    wallet = wallet_data if (wallet_ok and isinstance(wallet_data, dict)) else None
    
    # Identify which instance is this current VPS
    current_instance = None
    for inst in instances:
        inst_ip = inst.get("private_ip", "")
        if inst_ip == "10.10.10.66" or inst.get("name", "").lower() in ["shriyash-vps"]:
            inst["is_current_host"] = True
            current_instance = inst
        else:
            inst["is_current_host"] = False

    return {
        "configured": True,
        "connected": bool(vps_ok),
        "api_key_masked": f"{key[:8]}...{key[-6:]}" if len(key) > 14 else key,
        "instances": instances,
        "current_instance": current_instance,
        "wallet": wallet,
        "error": None if vps_ok else str(vps_data)
    }

