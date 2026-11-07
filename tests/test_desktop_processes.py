"""Exercise real Windows lifetime containment in an isolated GUI process."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest

@pytest.mark.skipif(os.name != 'nt', reason='Windows job objects')
@pytest.mark.parametrize('forced', [False, True])
def test_gui_job_cleans_descendants(tmp_path, forced):
    pidfile = tmp_path / 'child.pid'
    ready = tmp_path / 'ready'
    finish = tmp_path / 'finish'
    script = tmp_path / 'owner.py'
    script.write_text('''
import subprocess, sys, time
from pathlib import Path
from hostrun.desktop_processes import install
install()
child = subprocess.Popen([sys.executable, '-c', 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"]); time.sleep(120)'])
probe = subprocess.check_output([sys.executable, '-c', 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'], text=True)
assert probe.strip() == '0'
Path(sys.argv[1]).write_text(str(child.pid))
Path(sys.argv[2]).touch()
while not Path(sys.argv[3]).exists(): time.sleep(.05)
''')
    env = dict(os.environ, PYTHONPATH=str(Path.cwd()))
    owner = subprocess.Popen([sys.executable, str(script), str(pidfile), str(ready), str(finish)], env=env)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            assert owner.poll() is None
            time.sleep(.05)
        assert ready.exists()
        handle = kernel.OpenProcess(0x100000, False, int(pidfile.read_text()))
        assert handle
        if forced:
            owner.kill()
        else:
            finish.touch()
        owner.wait(timeout=10)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=10)
        if handle:
            kernel.CloseHandle(handle)
