"""Run file-backed shared-section capture and restore across fresh host processes."""
import ctypes
import errno
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


SIZE = 196608
OBJECT = 27
SLOT = 131072
ROOT = Path(__file__).resolve().parents[2]


def main(directory, mode):
    library = ctypes.CDLL(str(directory / 'libsection.dylib'))
    save = library.madeira_save_section_bytes
    load = library.madeira_load_section_bytes
    save.argtypes = load.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.c_int, ctypes.c_uint64]
    folder = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    with tempfile.TemporaryFile(dir=directory) as file:
        file.truncate(SIZE)
        with mmap.mmap(file.fileno(), SIZE) as view:
            if mode == 'save':
                struct.pack_into('<I', view, SLOT, 7)
                assert save(folder, OBJECT, file.fileno(), SIZE) == 0
                assert save(folder, OBJECT, file.fileno(), SIZE) == errno.EEXIST
            elif mode == 'resume':
                assert load(folder, OBJECT, file.fileno(), SIZE) == 0
                assert struct.unpack_from('<I', view, SLOT)[0] == 7
                # The child maps this one restored object at a different offset.
                subprocess.run([sys.executable, __file__, 'increment', str(file.fileno())],
                               check=True, pass_fds=(file.fileno(),))
                assert struct.unpack_from('<I', view, SLOT)[0] == 8
            elif mode == 'corrupt':
                assert load(folder, OBJECT, file.fileno(), SIZE) == errno.EBADMSG
            elif mode == 'truncated':
                assert load(folder, OBJECT, file.fileno(), SIZE) == errno.EINVAL
    os.close(folder)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'increment':
            with mmap.mmap(int(sys.argv[2]), SIZE - SLOT, offset=SLOT) as view:
                count, = struct.unpack_from('<I', view)
                assert count == 7
                struct.pack_into('<I', view, 0, count + 1)
        else:
            main(Path(sys.argv[2]), sys.argv[1])
    else:
        with tempfile.TemporaryDirectory(prefix='mdeck-section-') as tmp:
            directory = Path(tmp)
            subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', '-dynamiclib',
                            str(ROOT / 'build/wineserver/checkpoint_section.c'),
                            '-o', str(directory / 'libsection.dylib')], check=True)
            for mode in ('save', 'resume', 'corrupt', 'truncated'):
                if mode in ('corrupt', 'truncated'):
                    [section] = directory.glob('section-v1-*')
                    with section.open('r+b') as f:
                        if mode == 'corrupt':
                            f.write(b'X')
                        else:
                            f.truncate(SIZE)
                subprocess.run([sys.executable, __file__, mode, tmp], check=True)
        print('PASS fresh-process shared backing restore, shared offset aliases, duplicate save, corruption and truncation')
