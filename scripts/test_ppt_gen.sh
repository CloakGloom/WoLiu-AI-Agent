#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:17890
export https_proxy=http://127.0.0.1:17890
cd /mnt/i/Agent/tools/PPTAgent

echo "=== Starting PPTAgent ==="
echo "Args file: $1"
echo ""

python3 generate_ppt.py --args-file "$1" 2>&1
echo ""
echo "=== Exit code: $? ==="