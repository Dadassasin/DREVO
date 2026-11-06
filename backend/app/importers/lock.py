import json
import os
from contextlib import contextmanager


def import_active(settings):
    path = settings.data_dir / 'import.lock'
    try:
        pid = json.loads(path.read_text(encoding='utf-8'))['pid']
        if os.name == 'nt':
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ProcessLookupError, KeyError, ValueError):
        return False
    except PermissionError:
        return True


@contextmanager
def import_lock(settings):
    path = settings.data_dir / 'import.lock'
    if path.exists() and not import_active(settings):
        path.unlink(missing_ok=True)
    try:
        with path.open('x', encoding='utf-8') as stream:
            json.dump({'pid': os.getpid()}, stream)
    except FileExistsError:
        raise ValueError('Другой импорт уже выполняется')
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
