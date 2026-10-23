#!/bin/bash
set -euo pipefail
curl -fsS -m 20 -X POST http://127.0.0.1:8765/api/qemu -H 'content-type: application/json' -d '{"action":"stop"}'
