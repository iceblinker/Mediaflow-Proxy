import paramiko
import time
import sys

host = "138.199.156.62"
user = "root"
password = "M@rt1@n5"

def log(msg):
    print(f"[Inspect] {msg}")

try:
    log(f"Connecting to {host}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, look_for_keys=False, allow_agent=False)

    commands = [
        "echo '=== DISK USAGE ==='",
        "df -h /",
        "echo ''",
        "echo '=== MEMORY ==='",
        "free -h",
        "echo ''",
        "echo '=== CONTAINERS ==='",
        "/usr/local/bin/docker-compose -f ~/Mediaflow-Proxy/deploy/docker-compose.vps.yml ps",
        "echo ''",
        "echo '=== PROXY LOGS (Last 20) ==='",
        "docker logs --tail 20 mediaflow-proxy"
    ]

    full_command = " && ".join(commands)
    stdin, stdout, stderr = client.exec_command(full_command)
    
    # Read output
    print(stdout.read().decode('utf-8'))
    print(stderr.read().decode('utf-8'))
    
    client.close()
    log("Inspection Complete.")

except Exception as e:
    log(f"Error: {e}")
