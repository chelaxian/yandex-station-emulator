/* Redirect open/openat of /sys/class/leds → /mnt/leds (Mini 2 fake sysfs). */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static const char SRC[] = "/sys/class/leds";
static const char DST[] = "/mnt/leds";

static void rewrite(const char *path, char *out, size_t n) {
    size_t sl = sizeof(SRC) - 1;
    if (path && strncmp(path, SRC, sl) == 0 && (path[sl] == '/' || path[sl] == '\0')) {
        snprintf(out, n, "%s%s", DST, path + sl);
    } else if (path) {
        snprintf(out, n, "%s", path);
    } else {
        out[0] = 0;
    }
}

int open(const char *path, int flags, ...) {
    static int (*real_open)(const char *, int, ...) = NULL;
    mode_t mode = 0;
    char buf[512];
    if (!real_open) real_open = dlsym(RTLD_NEXT, "open");
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    rewrite(path, buf, sizeof(buf));
    if (flags & O_CREAT) return real_open(buf, flags, mode);
    return real_open(buf, flags);
}

int open64(const char *path, int flags, ...) {
    return open(path, flags);
}

int openat(int dirfd, const char *path, int flags, ...) {
    static int (*real_openat)(int, const char *, int, ...) = NULL;
    mode_t mode = 0;
    char buf[512];
    if (!real_openat) real_openat = dlsym(RTLD_NEXT, "openat");
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    if (path && path[0] == '/') {
        rewrite(path, buf, sizeof(buf));
        path = buf;
    }
    if (flags & O_CREAT) return real_openat(dirfd, path, flags, mode);
    return real_openat(dirfd, path, flags);
}
