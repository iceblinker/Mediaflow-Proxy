import paramiko

host = "138.199.156.62"
user = "root"
password = "M@rt1@n5"

def log(msg):
    print(f"[Check] {msg}")

try:
    log(f"Connecting to {host}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, look_for_keys=False, allow_agent=False)

    # Search for Caddyfile
    cmd = "find / -name Caddyfile 2>/dev/null"
    stdin, stdout, stderr = client.exec_command(cmd)
    
    files = stdout.read().decode('utf-8').strip().split('\n')
    
    if notfiles or files == ['']:
        log("No Caddyfile found!")
    else:
        for f in files:
            if f:
                log(f"Found: {f}")
                # Read it
                stdin, output, _ = client.exec_command(f"cat {f}")
                content = output.read().decode('utf-8')
                if "mediaflow-proxy" in content:
                    log(f"✅ Config FOUND in {f}")
                else:
                    log(f"❌ Config MISSING in {f}")

    client.close()

except Exception as e:
    log(f"Error: {e}")
