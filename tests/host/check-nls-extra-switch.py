#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 125hz
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""[nls-extra] env.MADEIRA_NLS_EXTRA: a code page table that is missing from nls/ may come from nls/extra/
(build/ntdll-unix/env_ios.c).

The switch is read at every request and defaults on, nls/ keeps priority, only code
page tables take the extra path, a missing extra file falls back to the original path, the log tags, and that
the locale fallback to LC_ALL is Wine's own (not a switch of this port).
"""
import re, sys, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
src = (ROOT / 'build/ntdll-unix/env_ios.c').read_text(encoding='utf-8', errors='replace')
failures = 0

def check(cond, text):
    global failures
    print(('PASS: ' if cond else 'FAIL: ') + text)
    if not cond: failures += 1

extra = src[src.index('static char *nls_extra_path( const char *dir, const char *name, char *path )'):]
extra = extra[:extra.index('\n}\n')]
check(re.search(r'const char \*e = getenv\( "MADEIRA_NLS_EXTRA" \);', extra) is not None and 'static int' not in extra,
      'the switch is read at every request, not cached')
check('if ((e && !strcmp( e, "0" )) || !access( path, R_OK )) return path;' in extra,
      'extra tables default on, explicit 0 disables, and nls/ always wins')
check('asprintf( &extra, "%s/nls/extra/%s.nls", dir, name )' in extra
      and 'if (access( extra, R_OK )) { free( extra ); return path; }' in extra,
      'the extra table is nls/extra/<name>.nls; when it is missing the original path is returned')
check('free( path );' in extra and 'return extra;' in extra, 'the original path is freed when the extra one is used')
check('[nls-extra] %s.nls comes from nls/extra (enabled by %s)' in extra and 'reports++ < 16' in extra,
      'each use is logged as [nls-extra], 16 lines at most')

path = src[src.index('static char *get_nls_file_path( UINT type, UINT id )'):]
path = path[:path.index('\n}\n')]
check('if (type == NLS_SECTION_CODEPAGE) path = nls_extra_path( dir, name, path );' in path,
      'only code page tables take the extra path (sort keys, case map, normalization do not)')
check(src.count('nls_extra_path(') == 2, 'one definition and one caller')
check('"[nls-missing] code page %u has no table (status %08x);' in src and 'missing_reports++ < 8' in src,
      'a code page with no table is logged as [nls-missing], eight lines at most')

loc = src[src.index('static BOOL unix_to_win_locale( const char *unix_name, char *win_name )'):]
loc = loc[:loc.index('\n}\n')]
check('unix_name = getenv( "LC_ALL" );' in loc and 'if (!unix_name || !unix_name[0] || !strcmp( unix_name, "C" ))' in loc,
      "LC_ALL is Wine's own fallback for an empty or C locale (no env. switch)")

catalog = ROOT / 'app/Madeira/ConfigCatalog.generated.swift'
if catalog.exists():
    text = catalog.read_text(encoding='utf-8')
    option = next(line for line in text.splitlines() if 'key: "env.MADEIRA_NLS_EXTRA"' in line)
    check('defaultValue: "1"' in option, 'the config catalog defaults env.MADEIRA_NLS_EXTRA to 1')

# Execute the production selector with real files, including live opt-out.
with tempfile.TemporaryDirectory(prefix='madeira-nls-') as directory:
    tmp = Path(directory)
    (tmp / 'nls/extra').mkdir(parents=True)
    (tmp / 'nls/extra/c_936.nls').write_bytes(b'extra fixture')
    harness = r'''
#define _DARWIN_C_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
/* SELECTOR */
static void expect(const char *dir, const char *name, const char *suffix) {
    char *path; assert(asprintf(&path, "%s/nls/%s.nls", dir, name) != -1);
    char *result = nls_extra_path(dir,name,path);
    char *wanted; assert(asprintf(&wanted, "%s/%s", dir,suffix) != -1);
    assert(!strcmp(result,wanted)); free(result); free(wanted);
}
int main(int argc, char **argv) {
    assert(argc == 2); const char *dir=argv[1];
    unsetenv("MADEIRA_NLS_EXTRA"); expect(dir,"c_936","nls/extra/c_936.nls");
    setenv("MADEIRA_NLS_EXTRA","0",1); expect(dir,"c_936","nls/c_936.nls");
    setenv("MADEIRA_NLS_EXTRA","1",1); expect(dir,"c_936","nls/extra/c_936.nls");
    unsetenv("MADEIRA_NLS_EXTRA"); expect(dir,"c_950","nls/c_950.nls");
    char *path; assert(asprintf(&path,"%s/nls/c_936.nls",dir) != -1);
    FILE *file=fopen(path,"w"); assert(file); fclose(file); free(path);
    expect(dir,"c_936","nls/c_936.nls");
    return 0;
}
'''
    c = tmp / 'selector.c'
    c.write_text(harness.replace('/* SELECTOR */', extra + '\n}'))
    binary = tmp / 'selector'
    subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(tmp)], check=True)
check(True, 'real selector: default/explicit on, live opt-out, missing extra and primary priority')

print(f'check-nls-extra-switch: {"OK" if not failures else f"{failures} FAILED"}')
sys.exit(1 if failures else 0)
