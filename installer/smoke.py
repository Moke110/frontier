"""Observe the installed console using native console APIs, with no PATH."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time

exe = Path(sys.argv[1]).resolve()
env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
env["PATH"] = ""
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
p = subprocess.Popen([str(exe)], env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
console = None
try:
    kernel.FreeConsole()
    deadline = time.monotonic() + 10
    while not kernel.AttachConsole(p.pid):
        if time.monotonic() >= deadline or p.poll() is not None:
            raise RuntimeError("Could not attach installed console")
        time.sleep(.1)
    title = ctypes.create_unicode_buffer(256)
    output = ctypes.create_unicode_buffer(256)
    count = wintypes.DWORD()
    console = kernel.CreateFileW("CONOUT$", 0x80000000, 3, None, 3, 0, None)
    if console == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    while time.monotonic() < deadline:
        kernel.GetConsoleTitleW(title, len(title))
        if not kernel.ReadConsoleOutputCharacterW(console, output, 255, 0, ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        if title.value == "Frontier Console" and "Hello World" in output.value:
            break
        time.sleep(.1)
    else:
        raise AssertionError(f"Unexpected console: {title.value!r}, {output.value!r}")
    time.sleep(2)
    assert p.poll() is None, "Console must remain open"
finally:
    if console is not None:
        kernel.CloseHandle(console)
    kernel.FreeConsole()
    if p.poll() is None:
        p.terminate()
    p.wait(timeout=10)
