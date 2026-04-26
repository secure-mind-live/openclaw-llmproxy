#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# OpenClaw LLM Proxy — One-Command VPS Setup
# ═══════════════════════════════════════════════════════════════════════════
#
# Automates the full VPS deployment:
#   1. Security hardening (SSH, firewall, fail2ban, auto-updates)
#   2. Non-root user creation with SSH key-only access
#   3. Tailscale VPN mesh (optional)
#   4. Docker + Docker Compose installation
#   5. OpenClaw LLM Proxy deployment
#   6. Ollama + Redis + PostgreSQL + Kafka
#   7. SSL via Caddy (optional)
#   8. Monitoring + smoke tests
#
# Usage (run as root on a fresh Ubuntu 22.04/24.04 VPS):
#   curl -sSL https://raw.githubusercontent.com/ParthaMehtaOrg/openclaw-llmproxy/main/scripts/vps_setup.sh | bash
#
# Or with options:
#   bash scripts/vps_setup.sh --user openclaw --domain llmproxy.example.com --tailscale-key tskey-auth-xxx
#
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────
DEPLOY_USER="${DEPLOY_USER:-openclaw}"
SSH_PORT="${SSH_PORT:-2222}"
DOMAIN="${DOMAIN:-}"
TAILSCALE_KEY="${TAILSCALE_KEY:-}"
PROXY_API_KEY="${PROXY_API_KEY:-$(openssl rand -base64 32)}"
INSTALL_DIR="/opt/openclaw-llmproxy"
REPO_URL="https://github.com/ParthaMehtaOrg/openclaw-llmproxy.git"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --user) DEPLOY_USER="$2"; shift 2 ;;
        --ssh-port) SSH_PORT="$2"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        --tailscale-key) TAILSCALE_KEY="$2"; shift 2 ;;
        --proxy-key) PROXY_API_KEY="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

step() { echo -e "\n${BLUE}═══ $1 ═══${NC}\n"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; exit 1; }

# ─── Preflight ───────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    fail "This script must be run as root"
fi

echo -e "${GREEN}"
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║     OpenClaw LLM Proxy — VPS Setup                ║"
echo "  ║                                                    ║"
echo "  ║     User:     $DEPLOY_USER"
echo "  ║     SSH Port: $SSH_PORT"
echo "  ║     Domain:   ${DOMAIN:-none (HTTP only)}"
echo "  ║     Tailscale: ${TAILSCALE_KEY:+enabled}${TAILSCALE_KEY:-disabled}"
echo "  ╚═══════════════════════════════════════════════════╝"
echo -e "${NC}"

sleep 3

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1: System Updates & Essential Packages
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 1: System updates and essential packages"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget ufw fail2ban ca-certificates gnupg \
    git unattended-upgrades apt-transport-https \
    software-properties-common jq htop

ok "System packages installed"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2: Create Non-Root User
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 2: Create non-root user '$DEPLOY_USER'"

if id "$DEPLOY_USER" &>/dev/null; then
    ok "User '$DEPLOY_USER' already exists"
else
    useradd -m -s /bin/bash -G sudo "$DEPLOY_USER"
    echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$DEPLOY_USER
    chmod 440 /etc/sudoers.d/$DEPLOY_USER

    # Copy SSH keys from root
    mkdir -p /home/$DEPLOY_USER/.ssh
    if [ -f /root/.ssh/authorized_keys ]; then
        cp /root/.ssh/authorized_keys /home/$DEPLOY_USER/.ssh/
    fi
    chown -R $DEPLOY_USER:$DEPLOY_USER /home/$DEPLOY_USER/.ssh
    chmod 700 /home/$DEPLOY_USER/.ssh
    chmod 600 /home/$DEPLOY_USER/.ssh/authorized_keys 2>/dev/null || true
    ok "User '$DEPLOY_USER' created with SSH keys"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3: Harden SSH
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 3: Harden SSH (port $SSH_PORT, key-only, no root login)"

cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

cat > /etc/ssh/sshd_config.d/hardened.conf <<EOF
Port $SSH_PORT
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers $DEPLOY_USER
EOF

# Test config before restarting
sshd -t && systemctl restart sshd
ok "SSH hardened on port $SSH_PORT (key-only, no root)"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4: Firewall (UFW)
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 4: Firewall — block everything, open what we need"

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow $SSH_PORT/tcp comment "SSH"

# Only open HTTP/HTTPS if we have a domain (public-facing)
if [ -n "$DOMAIN" ]; then
    ufw allow 80/tcp comment "HTTP"
    ufw allow 443/tcp comment "HTTPS"
fi

# If no Tailscale, open the proxy port directly
if [ -z "$TAILSCALE_KEY" ]; then
    ufw allow 8005/tcp comment "LLM Proxy"
fi

ufw --force enable
ok "Firewall active (SSH:$SSH_PORT${DOMAIN:+, HTTP:80, HTTPS:443})"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 5: Fail2Ban (auto-ban brute force)
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 5: Fail2Ban — auto-ban brute force SSH attempts"

cat > /etc/fail2ban/jail.local <<EOF
[sshd]
enabled = true
port = $SSH_PORT
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
findtime = 600
EOF

systemctl enable fail2ban
systemctl restart fail2ban
ok "Fail2Ban configured (3 attempts → 1hr ban)"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 6: Automatic Security Updates
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 6: Automatic security updates"

cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
EOF

systemctl enable unattended-upgrades
ok "Auto security updates enabled (reboot at 3am if needed)"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 7: Set Timezone & Entropy
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 7: System sanity (timezone, entropy)"

timedatectl set-timezone UTC
ok "Timezone set to UTC"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 8: Tailscale VPN (optional)
# ═══════════════════════════════════════════════════════════════════════════
if [ -n "$TAILSCALE_KEY" ]; then
    step "Phase 8: Tailscale VPN mesh"

    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up --authkey="$TAILSCALE_KEY" --ssh

    # Lock down to Tailscale only (close public SSH)
    ufw delete allow $SSH_PORT/tcp
    ufw allow in on tailscale0
    ufw reload

    ok "Tailscale connected — public SSH closed, VPN-only access"
else
    warn "Phase 8: Tailscale skipped (no --tailscale-key provided)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 9: Disable IPv6 (reduce attack surface)
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 9: Disable IPv6"

cat >> /etc/sysctl.d/99-disable-ipv6.conf <<EOF
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
sysctl --system > /dev/null 2>&1

ufw disable
ufw enable
ok "IPv6 disabled"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 10: Install Docker
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 10: Install Docker"

if command -v docker &>/dev/null; then
    ok "Docker already installed"
else
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker $DEPLOY_USER
    systemctl enable docker
    ok "Docker installed"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 11: Clone & Deploy OpenClaw LLM Proxy
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 11: Deploy OpenClaw LLM Proxy"

if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR"
    git pull
    ok "Repository updated"
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Repository cloned"
fi

cd "$INSTALL_DIR"
chown -R $DEPLOY_USER:$DEPLOY_USER "$INSTALL_DIR"

# Create .env file
cat > "$INSTALL_DIR/.env" <<EOF
PROXY_API_KEY=$PROXY_API_KEY
SECURITY_PII_MODE=redact
SECURITY_INJECTION_MODE=block
RATE_LIMIT_RPM=60
MAX_REQUEST_SIZE_MB=10
CACHE_TTL_S=3600
LOG_REDACT_BODIES=false
EOF
chmod 600 "$INSTALL_DIR/.env"
ok "Environment configured"

# Start with Docker Compose
sudo -u $DEPLOY_USER docker compose --env-file .env up -d --build
ok "Docker stack started"

# Pull Ollama model
echo "Pulling llama3.2:1b model (this may take a few minutes)..."
sudo -u $DEPLOY_USER docker compose exec -T ollama ollama pull llama3.2:1b
ok "Ollama model ready"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 12: SSL with Caddy (if domain provided)
# ═══════════════════════════════════════════════════════════════════════════
if [ -n "$DOMAIN" ]; then
    step "Phase 12: SSL with Caddy for $DOMAIN"

    apt-get install -y -qq debian-keyring debian-archive-keyring
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq caddy

    cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
    reverse_proxy localhost:8005 {
        flush_interval -1
    }
}
EOF

    systemctl enable caddy
    systemctl restart caddy
    ok "SSL enabled — https://$DOMAIN → proxy"
else
    warn "Phase 12: SSL skipped (no --domain provided)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 13: Systemd Services (backup if Docker restarts fail)
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 13: Systemd watchdog"

cat > /etc/systemd/system/openclaw-docker.service <<EOF
[Unit]
Description=OpenClaw LLM Proxy Docker Stack
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$DEPLOY_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose --env-file .env up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable openclaw-docker
ok "Systemd watchdog configured (auto-start on boot)"

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 14: Run Smoke Tests
# ═══════════════════════════════════════════════════════════════════════════
step "Phase 14: Smoke tests"

sleep 10  # Wait for containers to settle

PROXY_URL="http://localhost:8005"
if [ -n "$DOMAIN" ]; then
    PROXY_URL="https://$DOMAIN"
fi

if bash "$INSTALL_DIR/scripts/smoke_test.sh" "$PROXY_URL" "$PROXY_API_KEY"; then
    ok "All smoke tests passed"
else
    warn "Some smoke tests failed — check container logs: docker compose logs"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 15: Summary
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}"
echo "  ╔═══════════════════════════════════════════════════════════╗"
echo "  ║        OpenClaw LLM Proxy — Setup Complete                ║"
echo "  ╠═══════════════════════════════════════════════════════════╣"
echo "  ║                                                           ║"
echo "  ║  Proxy URL:   ${PROXY_URL}                               "
echo "  ║  Dashboard:   ${PROXY_URL}/dashboard                     "
echo "  ║  API Key:     ${PROXY_API_KEY}                           "
echo "  ║  SSH:         ssh -p $SSH_PORT $DEPLOY_USER@<your-ip>    "
echo "  ║  Install dir: $INSTALL_DIR                               "
echo "  ║                                                           ║"
echo "  ║  Security:                                                ║"
echo "  ║    - SSH on port $SSH_PORT (key-only, no root)           "
echo "  ║    - Fail2Ban active (3 attempts → 1hr ban)              "
echo "  ║    - UFW firewall enabled                                 ║"
echo "  ║    - Auto security updates (reboot at 3am)               ║"
echo "  ║    - IPv6 disabled                                        ║"
echo "  ║    - PII auto-redacted, injection auto-blocked           ║"
if [ -n "$TAILSCALE_KEY" ]; then
echo "  ║    - Tailscale VPN: public SSH closed                    ║"
fi
if [ -n "$DOMAIN" ]; then
echo "  ║    - SSL via Caddy: https://$DOMAIN                     "
fi
echo "  ║                                                           ║"
echo "  ║  Services running:                                        ║"
echo "  ║    - proxy (port 8005)     - redis (port 6379)           ║"
echo "  ║    - ollama (port 11434)   - postgres (port 5432)        ║"
echo "  ║    - kafka (port 9092)     - monitor (every 60s)         ║"
echo "  ║                                                           ║"
echo "  ║  Commands:                                                ║"
echo "  ║    docker compose logs -f monitor   # watch health        ║"
echo "  ║    docker compose logs -f proxy     # watch requests      ║"
echo "  ║    docker compose down              # stop everything     ║"
echo "  ║    docker compose up -d             # start everything    ║"
echo "  ╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
