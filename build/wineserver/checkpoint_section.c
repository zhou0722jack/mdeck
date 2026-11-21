#include "checkpoint_section.h"

#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Payload followed by a SHA-256 footer covering the format, identity, size
 * and payload. File names carry the format version. All integers used by
 * the digest are encoded in the canonical ASCII file name and size field. */
static int section_name(char name[48], uint64_t id, uint64_t size)
{
    if (!id || !size || size > INT64_MAX - CC_SHA256_DIGEST_LENGTH) return EINVAL;
    snprintf(name, 48, "section-v1-%016" PRIx64 "-%016" PRIx64, id, size);
    return 0;
}

static int verify_size(int fd, uint64_t size)
{
    struct stat st;
    if (fstat(fd, &st)) return errno;
    return S_ISREG(st.st_mode) && st.st_size >= 0 && (uint64_t)st.st_size == size ? 0 : EINVAL;
}

static int transfer(int fd, void *buffer, size_t size, off_t offset, int writing)
{
    unsigned char *p = buffer;
    while (size) {
        ssize_t n = writing ? pwrite(fd, p, size, offset) : pread(fd, p, size, offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return n < 0 ? errno : EIO;
        size -= (size_t)n;
        offset += n;
        p += n;
    }
    return 0;
}

static int copy_payload(int src, int dst, uint64_t size, const char *name,
                        unsigned char sum[CC_SHA256_DIGEST_LENGTH])
{
    const size_t chunk = 64 * 1024;
    void *buf = malloc(chunk);
    if (!buf) return ENOMEM;
    int err = 0;
    CC_SHA256_CTX hash;
    CC_SHA256_Init(&hash);
    CC_SHA256_Update(&hash, name, (CC_LONG)strlen(name));
    for (uint64_t pos = 0; pos < size; ) {
        size_t n = size - pos < chunk ? (size_t)(size - pos) : chunk;
        err = transfer(src, buf, n, (off_t)pos, 0);
        if (err) break;
        CC_SHA256_Update(&hash, buf, (CC_LONG)n);
        err = transfer(dst, buf, n, (off_t)pos, 1);
        if (err) break;
        pos += n;
    }
    CC_SHA256_Final(sum, &hash);
    free(buf);
    return err;
}

int madeira_save_section_bytes(int directory, uint64_t id, int backing, uint64_t size)
{
    char name[48], tmp[64];
    int err = section_name(name, id, size);
    if (!err) err = verify_size(backing, size);
    if (err) return err;
    snprintf(tmp, sizeof(tmp), ".section-%016" PRIx64 "-%08x-%08x", id,
             arc4random(), arc4random());
    int fd = openat(directory, tmp, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_CREAT | O_EXCL, 0600);
    if (fd == -1) return errno;
    unsigned char sum[CC_SHA256_DIGEST_LENGTH];
    err = copy_payload(backing, fd, size, name, sum);
    if (!err) err = transfer(fd, sum, sizeof(sum), (off_t)size, 1);
    if (!err && fsync(fd)) err = errno;
    if (close(fd) && !err) err = errno;
    if (!err && linkat(directory, tmp, directory, name, 0)) err = errno;
    unlinkat(directory, tmp, 0);
    return err;
}

int madeira_load_section_bytes(int directory, uint64_t id, int backing, uint64_t size)
{
    char name[48];
    int err = section_name(name, id, size);
    if (!err) err = verify_size(backing, size);
    if (err) return err;
    int fd = openat(directory, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd == -1) return errno;
    unsigned char actual[CC_SHA256_DIGEST_LENGTH], expected[CC_SHA256_DIGEST_LENGTH];
    err = verify_size(fd, size + sizeof(expected));
    if (!err) err = transfer(fd, expected, sizeof(expected), (off_t)size, 0);
    if (!err) err = copy_payload(fd, backing, size, name, actual);
    if (!err && memcmp(expected, actual, sizeof(expected))) err = EBADMSG;
    close(fd);
    return err;
}
