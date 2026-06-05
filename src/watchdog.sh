#!/bin/bash
# Prompt Gallery watchdog - checks server every 5 min, restarts if down
if ! curl -s -o /dev/null --max-time 3 http://localhost:8893/; then
    echo "[$(date)] Server down, restarting..." >> /Users/wanglingwei/Library/Logs/prompt-gallery-watchdog.log
    /opt/homebrew/bin/python3 "/Users/wanglingwei/Library/Application Support/remio/Users/F2313D5DDFE8FCF316DC1149F06BB14B/agent/prompt-gallery/src/serve.py" &
    sleep 2
    if curl -s -o /dev/null --max-time 3 http://localhost:8893/; then
        echo "[$(date)] Restart OK" >> /Users/wanglingwei/Library/Logs/prompt-gallery-watchdog.log
    else
        echo "[$(date)] Restart FAILED" >> /Users/wanglingwei/Library/Logs/prompt-gallery-watchdog.log
    fi
fi
