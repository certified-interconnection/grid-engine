import os, subprocess, sys, shutil
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "power-grid-model==1.13.217", "matpowercaseframes", "networkx"])
src = None
for root, dirs, files in os.walk("/kaggle/input"):
    if "gridengine" in dirs and "bench" in dirs:
        src = root; break
code = "/kaggle/working/code"; shutil.copytree(src, code, dirs_exist_ok=True)
subprocess.check_call([sys.executable, "bench/options_study.py", "case118", str(os.cpu_count())], cwd=code)
shutil.copytree(code + "/results", "/kaggle/working/results", dirs_exist_ok=True)
