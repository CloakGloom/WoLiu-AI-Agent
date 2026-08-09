#!/bin/bash
cd /mnt/i/Agent/tools/PPTAgent
echo "=== Python version ==="
python3 --version
echo "=== Testing import ==="
python3 -c "from deeppresenter.main import AgentLoop; print('Import OK')"
echo "=== Done ==="