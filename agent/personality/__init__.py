"""代理 —— side-projects/personality/"""
import os, importlib.util, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC  = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "side-projects", "personality")

def _load(name):
    path = os.path.join(_SRC, name)
    spec = importlib.util.spec_from_file_location("agent.personality." + name.replace(".py", ""), path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载: {path}")
    m = importlib.util.module_from_spec(spec)
    sys.modules[m.__name__] = m
    spec.loader.exec_module(m)
    return m

_init = _load("__init__.py")
for _k in dir(_init):
    if not _k.startswith("_"):
        globals()[_k] = getattr(_init, _k)
