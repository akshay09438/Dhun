# Loads the CANDIDATE validate.py content as app.planner.validate before tests import it.
import importlib.util, sys
CAND = r"C:\Users\Akshay\AppData\Local\Temp\claude\C--Users-Akshay-OneDrive-Desktop-DJ-AI-Official-Folder-for-claude\8f4ed0bb-cf0b-41c4-a153-4b44850c9a98\scratchpad\validate_k1.py"
spec = importlib.util.spec_from_file_location("app.planner.validate", CAND)
mod = importlib.util.module_from_spec(spec)
sys.modules["app.planner.validate"] = mod
spec.loader.exec_module(mod)
