#!/bin/bash

# optimize_vps.sh
# Run this script on your Linux VPS (Debian/Ubuntu) as root to enable BBR and tune networking.

echo ">>> Starting VPS Network Optimization..."

# 1. Enable TCP BBR (Bottleneck Bandwidth and RTT)
echo ">>> Enabling TCP BBR..."
if ! grep -q "net.core.default_qdisc=fq" /etc/sysctl.conf; then
    echo "net.core.default_qdisc=fq" | tee -a /etc/sysctl.conf
fi
if ! grep -q "net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf; then
    echo "net.ipv4.tcp_congestion_control=bbr" | tee -a /etc/sysctl.conf
fi

# 2. Network Tuning for High Throughput/Streaming
echo ">>> Tuning Kernel Network Settings..."
cat <<EOF | tee -a /etc/sysctl.conf
# Increase max open files
fs.file-max = 1000000

# Optimize TCP window sizes for high-bandwidth WAN connections
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Increase backlog for incoming connections
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 16384

# Enable TCP Fast Open (optional, helps latency)
net.ipv4.tcp_fastopen = 3

# Reduce standard TCP timeouts
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 1200
EOF

# 3. Apply Changes
echo ">>> Applying sysctl changes..."
sysctl -p

# 4. Set Ulimits persistence
echo ">>> Setting system-wide ulimits..."
if ! grep -q "root soft nofile 65535" /etc/security/limits.conf; then
    echo "* soft nofile 65535" | tee -a /etc/security/limits.conf
    echo "* hard nofile 65535" | tee -a /etc/security/limits.conf
    echo "root soft nofile 65535" | tee -a /etc/security/limits.conf
    echo "root hard nofile 65535" | tee -a /etc/security/limits.conf
fi

echo ">>> Optimization Complete! Please reboot your VPS to ensure all changes (especially ulimits) take full effect."
