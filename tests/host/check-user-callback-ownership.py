#!/usr/bin/env python3
"""Run production child PEB reset, builtin registration and callback guards."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def function(text, signature):
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]

classes = (ROOT / 'build/win32u-unix/class_ios.c').read_text()
loader = (ROOT / 'build/ntdll-unix/loader_ios.c').read_text()
signal = (ROOT / 'build/ntdll-unix/signal_arm64_ios.c').read_text()
reset = loader[loader.index('    child_peb->LdrData = NULL;'):loader.index("    /* Point child's TEB to the new PEB */")]
assert reset.count('child_peb->KernelCallbackTable = NULL;') == 1
assert loader.index('child_peb->KernelCallbackTable = NULL;') < loader.index('teb->Peb = child_peb;')
registry = classes[classes.index('struct ios_client_procs\n'):classes.index('/* Redirect a builtin winproc_array entry')]
callback = function(signal, 'NTSTATUS KeUserModeCallback(')
assert callback.index('!teb->Peb->KernelCallbackTable') < callback.index('get_syscall_frame()')
assert 'SESSION THREAD, CHILD DISPATCHER (BUG)' not in callback
assert '.hInstance = ios_cur_user32_module(),' in function(classes, 'static void register_builtin(')

fixture = (ROOT / 'tests/host/fixtures/UserCallbackOwnershipCheck.c').read_text()
pieces = {
    'REGISTRY': registry,
    'PEB_RESET': 'static void reset_child(PEB *child_peb) {\n' + reset + '\n}',
    'CALLBACK': callback,
    'BUILTINS': function(classes, 'void register_builtin_classes(void)'),
}
for name, text in pieces.items():
    assert fixture.count('// PRODUCTION_' + name) == 1
    fixture = fixture.replace('// PRODUCTION_' + name, text)
with tempfile.TemporaryDirectory(prefix='mdeck-user-callback-owner-') as temporary:
    folder = Path(temporary)
    source, binary = folder / 'check.c', folder / 'check'
    source.write_text(fixture)
    subprocess.run(['xcrun', 'clang', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-pthread',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('ASan/UBSan host regression only; no FEX modification, Steam/Wine execution, IPA build or physical-device acceptance.')
