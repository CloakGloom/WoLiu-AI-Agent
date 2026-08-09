#!/bin/bash
echo "Test 1: Python version"
python3 --version 2>&1

echo "Test 2: Simple print"
python3 -c 'print("hello world")' 2>&1

echo "Test 3: Import pptagent"
cd /mnt/i/Agent/tools/PPTAgent
python3 -c 'from pptagent import PPTAgentServer; print("OK")' 2>&1

echo "Test 4: Import deeppresenter config"
python3 -c 'from deeppresenter.utils.config import DeepPresenterConfig; c = DeepPresenterConfig.load_from_file(); print("offline_mode:", c.offline_mode)' 2>&1

echo "=== All tests done ==="