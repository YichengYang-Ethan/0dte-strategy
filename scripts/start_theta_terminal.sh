#!/bin/bash
# Start Theta Terminal in the background.
#
# Prereqs:
#   1. Java installed: `brew install openjdk` (macOS)
#   2. ThetaTerminal.jar downloaded to ~/theta-terminal/
#        mkdir -p ~/theta-terminal
#        cd ~/theta-terminal
#        curl -L -o ThetaTerminal.jar https://download-unstable.thetadata.us/ThetaTerminalv3.jar
#   3. THETA_USERNAME + THETA_PASSWORD set in .env
#
# Usage:
#   scripts/start_theta_terminal.sh
#
# Verification: http://127.0.0.1:25510/v2/system/mdds/status should return CONNECTED

set -euo pipefail

# Prefer Homebrew openjdk@21 (Apple Silicon default path). Fall back to system java.
if [ -d "/opt/homebrew/opt/openjdk@21/bin" ]; then
    export PATH="/opt/homebrew/opt/openjdk@21/bin:$PATH"
fi

THETA_DIR="${THETA_DIR:-$HOME/theta-terminal}"
JAR="$THETA_DIR/ThetaTerminal.jar"
CREDS_FILE="$THETA_DIR/creds.txt"
LOG_DIR="$THETA_DIR/logs"
PID_FILE="$THETA_DIR/terminal.pid"
# v3 API (Terminal >= 20260327 build). Ports: 25503 REST, 25520 WS.
REST_URL="http://127.0.0.1:25503/v3/option/list/symbols"
HEALTH_TIMEOUT_SEC=90

# Load env (robust to values with $ " \ etc.)
if [ -f .env ]; then
    set -o allexport
    # shellcheck disable=SC1091
    source .env
    set +o allexport
fi

: "${THETA_USERNAME:?THETA_USERNAME not set (edit .env)}"
: "${THETA_PASSWORD:?THETA_PASSWORD not set (edit .env)}"

if [ ! -f "$JAR" ]; then
    echo "ERROR: $JAR not found"
    echo "Download it:"
    echo "  mkdir -p $THETA_DIR"
    echo "  curl -L -o $JAR https://download-unstable.thetadata.us/ThetaTerminalv3.jar"
    echo "  file $JAR   # verify it's a Java archive, not an HTML error page"
    exit 1
fi

# Verify jar is actually a Java archive, not an HTML error page
if ! file "$JAR" | grep -qiE "zip archive|java archive"; then
    echo "ERROR: $JAR is not a valid Java archive"
    echo "Downloaded content:"
    file "$JAR"
    head -c 200 "$JAR"
    echo ""
    echo "Re-download from https://thetadata.net/download or check current URL"
    exit 1
fi

if ! command -v java >/dev/null 2>&1; then
    echo "ERROR: java not found"
    echo "Install (Apple Silicon):"
    echo "  brew install openjdk@21"
    echo "  sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk \\"
    echo "    /Library/Java/JavaVirtualMachines/openjdk-21.jdk"
    exit 1
fi

echo "Java: $(java -version 2>&1 | head -1)"
echo "Jar:  $JAR ($(du -h "$JAR" | awk '{print $1}'))"

# Ensure creds.txt exists (v3 requires --creds-file, not positional args)
if [ ! -f "$CREDS_FILE" ]; then
    printf "%s\n%s\n" "$THETA_USERNAME" "$THETA_PASSWORD" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"
    echo "Created $CREDS_FILE (chmod 600)"
fi

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Terminal already running (pid $(cat "$PID_FILE"))"
else
    mkdir -p "$LOG_DIR"
    LOG="$LOG_DIR/terminal-$(date +%Y%m%d-%H%M%S).log"
    echo "Starting Theta Terminal, logging to $LOG"
    cd "$THETA_DIR"
    nohup java -jar "$JAR" --creds-file "$CREDS_FILE" \
        > "$LOG" 2>&1 &
    echo $! > "$PID_FILE"
    cd - > /dev/null
    echo "Started pid $(cat "$PID_FILE")"
fi

# Wait for health
echo "Waiting for Terminal health (up to ${HEALTH_TIMEOUT_SEC}s)..."
deadline=$(($(date +%s) + HEALTH_TIMEOUT_SEC))
while [ "$(date +%s)" -lt "$deadline" ]; do
    resp=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$REST_URL" || echo "000")
    if [ "$resp" = "200" ]; then
        echo "Health check: HTTP 200 from /v3/option/list/symbols"
        echo ""
        echo "Terminal ready at http://127.0.0.1:25503 (REST) + ws://127.0.0.1:25520 (WS)"
        exit 0
    fi
    sleep 2
done

echo "ERROR: Terminal did not reach healthy state in ${HEALTH_TIMEOUT_SEC}s"
echo "Check log: $LOG"
exit 2
