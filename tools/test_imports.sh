#!/bin/bash
cd /mnt/i/Agent/tools/PPTAgent
echo "=== Testing imports ==="
python -c '
import sys
print("Python version:", sys.version)
print("Importing deeppresenter...")
try:
    from deeppresenter.main import AgentLoop
    print("AgentLoop OK")
except Exception as e:
    print(f"AgentLoop FAIL: {e}")

try:
    from deeppresenter.utils.config import DeepPresenterConfig
    print("DeepPresenterConfig OK")
except Exception as e:
    print(f"DeepPresenterConfig FAIL: {e}")

try:
    from pptagent import PPTAgentServer
    print("PPTAgentServer OK")
except Exception as e:
    print(f"PPTAgentServer FAIL: {e}")
' 2>&1