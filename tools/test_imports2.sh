#!/bin/bash
cd /mnt/i/Agent/tools/PPTAgent
python -c '
import sys
with open("/tmp/test_output.txt", "w") as f:
    f.write("Python version: " + sys.version + "\n")
    try:
        from pptagent import PPTAgentServer
        f.write("PPTAgentServer import OK\n")
    except Exception as e:
        f.write("PPTAgentServer import FAIL: " + str(e) + "\n")
    
    try:
        from deeppresenter.utils.config import DeepPresenterConfig
        f.write("DeepPresenterConfig import OK\n")
        config = DeepPresenterConfig.load_from_file()
        f.write("Config loaded: " + str(config.offline_mode) + "\n")
    except Exception as e:
        f.write("DeepPresenterConfig FAIL: " + str(e) + "\n")
'
cat /tmp/test_output.txt 2>&1