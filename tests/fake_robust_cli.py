import json
import os
import subprocess
import sys
import time
from pathlib import Path

mode = sys.argv[1]
if mode == "break":
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole()
    if not kernel.AttachConsole(int(sys.argv[2])):
        raise ctypes.WinError(ctypes.get_last_error())
    handler = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(lambda event: True)
    kernel.SetConsoleCtrlHandler(handler, True)
    if not kernel.GenerateConsoleCtrlEvent(1, int(sys.argv[2])):
        raise ctypes.WinError(ctypes.get_last_error())
    time.sleep(0.2)
    kernel.FreeConsole()
elif mode == "child":
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(120)
elif mode == "tree":
    child = subprocess.Popen([sys.executable, __file__, "child", sys.argv[2]])
    while not Path(sys.argv[2]).exists():
        time.sleep(0.01)
    if len(sys.argv) < 4:
        time.sleep(120)
    print("Outcome: tree started.")
elif mode == "quiet":
    time.sleep(float(sys.argv[2]))
    print(json.dumps({"result": "Completed quietly.", "usage": {"input_tokens": 3}}))
else:
    print("STATUS: DONE\nSUMMARY: Completed fixture.")
