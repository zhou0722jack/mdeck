/* Bundled Simplified Chinese font support, applied before wineserver starts. */
#ifndef MADEIRA_CHINESE_FONTS_H
#define MADEIRA_CHINESE_FONTS_H
#import <Foundation/Foundation.h>

extern void ws_log(const char *fmt, ...);

static NSString *madeira_font_reg_escape(NSString *value)
{
    NSMutableString *escaped = [NSMutableString string];
    for (NSUInteger i = 0; i < value.length; i++) {
        unichar c = [value characterAtIndex:i];
        if (c == '\\') [escaped appendString:@"\\\\"];
        else if (c == '"') [escaped appendString:@"\\\""];
        else if (c < 0x20 || c > 0x7e) [escaped appendFormat:@"\\x%04x", c];
        else [escaped appendFormat:@"%C", c];
    }
    return escaped;
}

/* Keep custom aliases and link order. Only append our face to string-form
 * REG_MULTI_SZ lists; unfamiliar encodings are left intact. */
static BOOL madeira_font_registry_merge(NSString *path, NSString *section,
                                        NSDictionary<NSString *, NSString *> *values, BOOL links)
{
    NSString *original = [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
    if (!original.length) return NO;
    NSMutableArray<NSString *> *lines = [[original componentsSeparatedByString:@"\n"] mutableCopy];
    NSString *header = [NSString stringWithFormat:@"[%@]", [section lowercaseString]];
    NSUInteger start = NSNotFound;
    for (NSUInteger i = 0; i < lines.count; i++) {
        if ([[lines[i] lowercaseString] hasPrefix:header]) { start = i; break; }
    }
    if (start == NSNotFound) {
        [lines addObject:@""];
        [lines addObject:[NSString stringWithFormat:@"[%@]", section]];
        start = lines.count - 1;
    }
    NSUInteger end = start + 1;
    while (end < lines.count && ![lines[end] hasPrefix:@"["]) end++;
    for (NSString *name in [[values allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
        NSString *key = [NSString stringWithFormat:@"\"%@\"=", madeira_font_reg_escape(name)];
        NSUInteger found = NSNotFound;
        for (NSUInteger i = start + 1; i < end; i++) {
            if ([[lines[i] lowercaseString] hasPrefix:[key lowercaseString]]) { found = i; break; }
        }
        if (found == NSNotFound) {
            [lines insertObject:[key stringByAppendingString:values[name]] atIndex:end++];
        } else if (links) {
            NSString *value = [lines[found] substringFromIndex:key.length];
            if ([value hasPrefix:@"str(7):\""] && [value hasSuffix:@"\""] &&
                [value rangeOfString:@"NotoSansSC-Regular.otf" options:NSCaseInsensitiveSearch].location == NSNotFound) {
                NSString *old = [value substringToIndex:value.length - 1];
                /* A nonempty previous list must end with a NUL separator. */
                NSString *separator = old.length > 8 && ![old hasSuffix:@"\\0"] ? @"\\0" : @"";
                lines[found] = [NSString stringWithFormat:@"%@%@%@NotoSansSC-Regular.otf,Noto Sans SC\\0\"", key, old, separator];
            }
        }
    }
    NSString *updated = [lines componentsJoinedByString:@"\n"];
    if (![updated hasSuffix:@"\n"]) updated = [updated stringByAppendingString:@"\n"];
    if ([updated isEqualToString:original]) return YES;
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *backup = [path stringByAppendingString:@".madeira-fonts-bak"];
    if (![fm fileExistsAtPath:backup] && ![fm copyItemAtPath:path toPath:backup error:nil]) return NO;
    return [updated writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
}

static BOOL madeira_chinese_fonts(NSString *prefix, NSString *resources)
{
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *name = @"NotoSansSC-Regular.otf";
    NSString *source = [[resources stringByAppendingPathComponent:@"fonts-zh"] stringByAppendingPathComponent:name];
    NSData *font = [NSData dataWithContentsOfFile:source options:NSDataReadingMappedIfSafe error:nil];
    if (!font.length) { ws_log("[chinese-font] bundled Noto Sans SC is missing; prefix left unchanged"); return NO; }
    NSString *directory = [prefix stringByAppendingPathComponent:@"drive_c/windows/Fonts"];
    NSString *destination = [directory stringByAppendingPathComponent:name];
    NSData *installed = [NSData dataWithContentsOfFile:destination options:NSDataReadingMappedIfSafe error:nil];
    BOOL copied = ![font isEqualToData:installed];
    if (copied && (![fm createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil] ||
                   ![font writeToFile:destination options:NSDataWritingAtomic error:nil])) {
        ws_log("[chinese-font] could not install Noto Sans SC"); return NO;
    }
    NSMutableDictionary<NSString *, NSString *> *aliases = [NSMutableDictionary dictionary];
    for (NSString *alias in @[@"SimSun", @"NSimSun", @"SimHei", @"Microsoft YaHei", @"Microsoft YaHei UI",
                              @"\u5b8b\u4f53", @"\u65b0\u5b8b\u4f53", @"\u9ed1\u4f53", @"\u5fae\u8f6f\u96c5\u9ed1"])
        aliases[alias] = @"\"Noto Sans SC\"";
    BOOL replacements = madeira_font_registry_merge([prefix stringByAppendingPathComponent:@"user.reg"],
        @"Software\\\\Wine\\\\Fonts\\\\Replacements", aliases, NO);
    NSString *system = [prefix stringByAppendingPathComponent:@"system.reg"];
    BOOL registered = madeira_font_registry_merge(system,
        @"Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts",
        @{@"Noto Sans SC (TrueType)": @"\"NotoSansSC-Regular.otf\""}, NO);
    NSMutableDictionary<NSString *, NSString *> *links = [NSMutableDictionary dictionary];
    for (NSString *face in @[@"Tahoma", @"Tahoma Bold", @"Arial", @"Microsoft Sans Serif", @"Segoe UI", @"System"])
        links[face] = @"str(7):\"NotoSansSC-Regular.otf,Noto Sans SC\\0\"";
    BOOL linked = madeira_font_registry_merge(system,
        @"Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\FontLink\\\\SystemLink", links, YES);
    ws_log("[chinese-font] Noto Sans SC %s; aliases=%d registered=%d fallback=%d",
           copied ? "installed" : "verified", replacements, registered, linked);
    return replacements && registered && linked;
}
#endif
