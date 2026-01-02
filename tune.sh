#!/bin/bash
# Check for root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

echo "Applying Premium Network Optimizations..."

# 1. Enable TCP BBR (Congestion Control)
modprobe tcp_bbr
if ! grep -q "net.core.default_qdisc=fq" /etc/sysctl.conf; then
    echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
fi
if ! grep -q "net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf; then
    echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
fi

# 2. Increase Network Buffer Sizes (Crucial for 4K segments)
cat <<EOF | tee -a /etc/sysctl.conf
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.ipv4.tcp_rmem=4096 87380 16777216
net.ipv4.tcp_wmem=4096 65536 16777216
EOF

# 3. Increase Max Connections & Backlog
cat <<EOF | tee -a /etc/sysctl.conf
net.core.somaxconn=4096
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.tcp_slow_start_after_idle=0
EOF

# 4. Fast Open for lower latency
if ! grep -q "net.ipv4.tcp_fastopen=3" /etc/sysctl.conf; then
    echo "net.ipv4.tcp_fastopen=3" >> /etc/sysctl.conf
fi

# Apply changes
sysctl -p

# 5. Increase System File Limits
if ! grep -q "soft nofile 65535" /etc/security/limits.conf; then
    echo "* soft nofile 65535" >> /etc/security/limits.conf
    echo "* hard nofile 65535" >> /etc/security/limits.conf
fi

echo "Optimization Complete. Restart your Docker containers to apply ulimits."
