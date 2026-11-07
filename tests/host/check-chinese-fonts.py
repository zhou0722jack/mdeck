#!/usr/bin/env python3
"""Check the actual font and production prefix migration without starting Wine."""
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
manifest = json.loads((APP / 'fonts-zh/source.json').read_text())
font = APP / 'fonts-zh' / manifest['file']
assert hashlib.sha256(font.read_bytes()).hexdigest() == manifest['sha256']
assert 'SIL OPEN FONT LICENSE' in (APP / 'fonts-zh/LICENSE-NotoSansSC-OFL-1.1.txt').read_text()
project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
assert 'fonts-zh in Resources' in project and 'path = "fonts-zh"' in project
bridge = (APP / 'WineProcessBridge.m').read_text()
assert '#include "ChineseFonts.h"' in bridge
seed = bridge[bridge.index('void madeira_seed_prefix_if_needed('):bridge.index('/* ===========================================================================', bridge.index('void madeira_seed_prefix_if_needed('))]
assert 'madeira_chinese_fonts( prefix, NSBundle.mainBundle.resourcePath );' in seed
server = (APP / 'WineServerBridge.m').read_text()
assert server.index('madeira_seed_prefix_if_needed(prefix_path)') < server.index('pthread_create(', server.index('madeira_seed_prefix_if_needed(prefix_path)'))

harness = r'''
#import <Foundation/Foundation.h>
#import <CoreText/CoreText.h>
#include <assert.h>
#include "ChineseFonts.h"
void ws_log(const char *fmt, ...) { (void)fmt; }
static NSString *read_registry(NSString *path) { return [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil]; }
static NSString *registry_section(NSString *text, NSString *name) {
    NSRange start = [text rangeOfString:[NSString stringWithFormat:@"[%@]", name]];
    assert(start.location != NSNotFound);
    NSRange next = [text rangeOfString:@"\n[" options:0 range:NSMakeRange(NSMaxRange(start), text.length - NSMaxRange(start))];
    return [text substringWithRange:NSMakeRange(start.location, (next.location == NSNotFound ? text.length : next.location) - start.location)];
}
int main(int argc, char **argv) {
    @autoreleasepool {
        assert(argc == 3);
        NSString *prefix = @(argv[1]), *resources = @(argv[2]);
        NSString *user = [prefix stringByAppendingPathComponent:@"user.reg"];
        NSString *system = [prefix stringByAppendingPathComponent:@"system.reg"];
        NSString *beforeUser = read_registry(user), *beforeSystem = read_registry(system);
        assert(madeira_chinese_fonts(prefix, resources));
        NSString *afterUser = read_registry(user), *afterSystem = read_registry(system);
        assert([afterUser containsString:@"\"SimSun\"=\"Custom Han\""]);
        assert([afterUser containsString:@"\"NSimSun\"=\"Noto Sans SC\""]);
        assert([afterUser containsString:@"\"Noto Sans CJK SC\"=\"Noto Sans SC\""]);
        assert([afterUser containsString:@"\"\\x5b8b\\x4f53\"=\"Noto Sans SC\""]);
        assert([afterUser containsString:@"\"Unrelated\"=\"keep\""]);
        assert([afterSystem containsString:@"\"Tahoma\"=str(7):\"CUSTOM.TTF,Custom\\0NotoSansSC-Regular.otf,Noto Sans SC\\0\""]);
        assert([afterSystem containsString:@"\"Arial\"=hex(7):41,00,00,00"]);
        assert([afterSystem containsString:@"\"Noto Sans SC (TrueType)\"=\"NotoSansSC-Regular.otf\""]);
        NSString *view32 = registry_section(afterSystem, @"Software\\\\Wow6432Node\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts");
        NSString *view64 = registry_section(afterSystem, @"Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts");
        assert([view32 containsString:@"\"Noto Sans SC (TrueType)\"=\"NotoSansSC-Regular.otf\""]);
        assert([view64 containsString:@"\"Noto Sans SC (TrueType)\"=\"NotoSansSC-Regular.otf\""]);
        assert([view32 containsString:@"\"Tahoma (TrueType)\"=\"tahoma.ttf\""]);
        assert([read_registry([user stringByAppendingString:@".madeira-fonts-bak"]) isEqualToString:beforeUser]);
        assert([read_registry([system stringByAppendingString:@".madeira-fonts-bak"]) isEqualToString:beforeSystem]);
        NSString *linkFile = [prefix stringByAppendingPathComponent:@"linked.reg"];
        NSString *linkText = @"WINE REGISTRY Version 2\n\n[Software\\\\Wow6432Node\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts]\n#link\n\"SymbolicLinkValue\"=str(6):\"keep\"\n";
        assert([linkText writeToFile:linkFile atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        assert(madeira_font_registry_merge(linkFile, @"Software\\\\Wow6432Node\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts",
            @{@"Noto Sans SC (TrueType)": @"\"NotoSansSC-Regular.otf\""}, NO));
        assert([read_registry(linkFile) isEqualToString:linkText]);
        NSString *installed = [prefix stringByAppendingPathComponent:@"drive_c/windows/Fonts/NotoSansSC-Regular.otf"];
        NSData *font = [NSData dataWithContentsOfFile:installed];
        assert(font.length > 8000000);
        /* Repeat launch is byte-identical; previous backups remain intact. */
        assert(madeira_chinese_fonts(prefix, resources));
        assert([read_registry(user) isEqualToString:afterUser] && [read_registry(system) isEqualToString:afterSystem]);
        assert([read_registry([system stringByAppendingString:@".madeira-fonts-bak"]) isEqualToString:beforeSystem]);
        /* An interrupted/corrupt owned font is repaired; a missing bundle
         * must not add registry mappings or truncate an existing font. */
        assert([[@"broken" dataUsingEncoding:NSUTF8StringEncoding] writeToFile:installed atomically:YES]);
        assert(madeira_chinese_fonts(prefix, resources));
        assert([[NSData dataWithContentsOfFile:installed] isEqualToData:font]);
        assert(!madeira_chinese_fonts(prefix, [resources stringByAppendingPathComponent:@"absent"]));
        assert([read_registry(user) isEqualToString:afterUser] && [[NSData dataWithContentsOfFile:installed] isEqualToData:font]);
        CFArrayRef descriptors = CTFontManagerCreateFontDescriptorsFromURL((__bridge CFURLRef)[NSURL fileURLWithPath:installed]);
        assert(descriptors && CFArrayGetCount(descriptors) == 1);
        CTFontRef face = CTFontCreateWithFontDescriptor(CFArrayGetValueAtIndex(descriptors, 0), 14, NULL);
        CFStringRef family = CTFontCopyFamilyName(face);
        assert(CFEqual(family, CFSTR("Noto Sans SC")));
        NSString *sample = @"欢迎使用 Steam 安装向导 下一步 取消 简体中文 字体测试 软件 微软雅黑 宋体 0123456789";
        UniChar chars[256]; CGGlyph glyphs[256];
        [sample getCharacters:chars range:NSMakeRange(0, sample.length)];
        assert(CTFontGetGlyphsForCharacters(face, chars, glyphs, sample.length));
        for (NSUInteger i=0; i<sample.length; i++) assert(glyphs[i]);
        CFRelease(family); CFRelease(face); CFRelease(descriptors);
    }
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='madeira-fonts-') as directory:
    tmp = Path(directory)
    prefix = tmp / 'prefix'
    prefix.mkdir()
    with tarfile.open(APP / 'prefix-template.tar.gz') as archive:
        for filename in ['user.reg', 'system.reg']:
            data = archive.extractfile('prefix/' + filename).read().decode()
            if filename == 'user.reg':
                pos = data.index('\n', data.index('[Software\\\\Wine\\\\Fonts\\\\Replacements]'))
                data = data[:pos] + '\n"SimSun"="Custom Han"\n"Unrelated"="keep"' + data[pos:]
            else:
                pos = data.index('\n', data.index('FontLink\\\\SystemLink]'))
                # Replace existing links for these names, then insert custom fixtures.
                start = data.rfind('[', 0, pos)
                end = data.find('\n[', pos)
                section = data[start:end]
                section = '\n'.join(line for line in section.splitlines() if not line.startswith(('"Tahoma"=', '"Arial"=')))
                section += '\n"Tahoma"=str(7):"CUSTOM.TTF,Custom\\0"\n"Arial"=hex(7):41,00,00,00\n'
                data = data[:start] + section + data[end:]
            (prefix / filename).write_text(data)
    source = tmp / 'check.m'
    source.write_text(harness)
    binary = tmp / 'check'
    subprocess.run(['clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-I', str(APP), str(source),
                    '-framework', 'Foundation', '-framework', 'CoreText', '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(prefix), str(APP)], check=True)
print('PASS: pinned font hash, bundled licence, family and Simplified Chinese glyph coverage')
print('PASS: existing-prefix install, custom aliases/link order, unknown encodings, backups and idempotence')
print('PASS: 32/64-bit font registry views, DirectWrite CJK family alias and registry-link preservation')
print('PASS: corrupt font repair, missing bundle, registration and seeding before wineserver')
