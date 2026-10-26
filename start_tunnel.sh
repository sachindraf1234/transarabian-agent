#!/usr/bin/env bash
#
# start_tunnel.sh - a PERMANENT bridge from Meta to this agent.
#
# Why this exists
# ---------------
# The free Cloudflare quick tunnel issues a new random URL every time it starts,
# which means re-pasting the callback URL into Meta again and again. This uses
# YOUR ngrok account instead, so the domain is yours and never changes.
#
#   Meta  ->  https://YOUR-DOMAIN.ngrok-free.app  ->  ngrok  ->  this agent :8000
#
# What you need (both free)
# -------------------------
#   1. An ngrok authtoken :  dashboard.ngrok.com/get-started/your-authtoken
#   2. A static domain    :  dashboard.ngrok.com/domains  (free plan gives one)
#
# How to run
# ----------
#   NGROK_AUTHTOKEN=2abc... NGROK_DOMAIN=your-name.ngrok-free.app ./start_tunnel.sh
#
set -euo pipefail

NGROK=/home/user/ngrok
PORT="${PORT:-8000}"

if [ -z "${NGROK_AUTHTOKEN:-}" ] || [ -z "${NGROK_DOMAIN:-}" ]; then
    echo
    echo "  Missing credentials."
    echo
    echo "    NGROK_AUTHTOKEN=your_token NGROK_DOMAIN=your-name.ngrok-free.app \\"
    echo "      ./start_tunnel.sh"
    echo
    echo "  Get them free from dashboard.ngrok.com - authtoken under"
    echo "  'Your Authtoken', domain under 'Domains'."
    echo
    exit 1
fi

# install the binary if a restart wiped it
if [ ! -x "$NGROK" ]; then
    echo "  ngrok missing - downloading..."
    curl -sL -o /home/user/ngrok.tgz \
        https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
    tar -xzf /home/user/ngrok.tgz -C /home/user
    chmod +x "$NGROK"
fi

"$NGROK" config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null

# Keep the agent's own idea of its public address in step with the tunnel.
# Getting this wrong is what kept breaking the Meta handshake before.
ENV_FILE=/home/user/transarabian-agent/.env
if [ -f "$ENV_FILE" ]; then
    python3 - "$ENV_FILE" "$NGROK_DOMAIN" <<'PY'
import re, sys
path, domain = sys.argv[1], sys.argv[2].strip()
src = open(path, encoding="utf-8").read()
new, n = re.subn(r"(?m)^PUBLIC_BASE_URL=.*$",
                 f"PUBLIC_BASE_URL=https://{domain}", src)
if not n:
    src = src.rstrip("\n") + f"\nPUBLIC_BASE_URL=https://{domain}\n"
    new = src
open(path, "w", encoding="utf-8").write(new)
print(f"  .env PUBLIC_BASE_URL -> https://{domain}")
PY
fi

echo
echo "  bridging  https://${NGROK_DOMAIN}  ->  localhost:${PORT}"
echo "  callback for Meta:  https://${NGROK_DOMAIN}/webhook"
echo

exec "$NGROK" http --url="$NGROK_DOMAIN" "$PORT"
