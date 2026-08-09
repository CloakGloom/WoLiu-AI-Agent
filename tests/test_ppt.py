import sys
sys.path.insert(0, 'i:/Agent')
try:
    from pptx import Presentation
    print("pptx import OK")
except Exception as e:
    print("IMPORT ERROR:", e)
    import traceback
    traceback.print_exc()

try:
    from agent.tools.custom.ppt_generator import generate_ppt
    r = generate_ppt('Test', 'Sub', [{'slide_title': 'Page1', 'bullets': ['A', 'B']}])
    print("RESULT:", r)
except Exception as e:
    print("PPT ERROR:", e)
    import traceback
    traceback.print_exc()