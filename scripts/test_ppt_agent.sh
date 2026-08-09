#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:17890
export https_proxy=http://127.0.0.1:17890
cd /mnt/i/Agent/tools/PPTAgent

echo "=== Testing config load ==="
python3 -c "
from deeppresenter.utils.config import DeepPresenterConfig
from pathlib import Path
config = DeepPresenterConfig.load_from_file('/mnt/i/Agent/tools/PPTAgent/deeppresenter/config.yaml')
print('Config loaded OK')
print('Model:', config.design_agent.model)
print('Base URL:', config.design_agent.base_url)
"

echo ""
echo "=== Testing API connectivity ==="
python3 -c "
import urllib.request
import json
req = urllib.request.Request('https://api.deepseek.com/v1/models')
req.add_header('Authorization', 'Bearer ${DEEPSEEK_API_KEY}')
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print('API OK, status:', resp.status)
except Exception as e:
    print('API FAIL:', e)
"