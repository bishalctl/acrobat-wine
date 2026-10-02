/* Standalone Nix-closure entry point.
 * The host filesystem stays visible with the launching user's UID and groups.
 * A complete host Nix closure can run directly. Otherwise a private mount
 * namespace merges the embedded closure with any host Nix store, preserving
 * access to host graphics drivers and to ordinary files at the root of /.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/types.h>
#include <unistd.h>

static void fail(const char *operation, const char *path)
{
    int error = errno;
    char message[PATH_MAX + 256];
    snprintf(message, sizeof(message), "Acrobat AppImage: %s %s: %s", operation, path, strerror(error));
    fprintf(stderr, "%s\n", message);
    /* Log failures that happen before the Python launcher can start. */
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd >= 0) {
        struct sockaddr_un address = { .sun_family = AF_UNIX };
        strcpy(address.sun_path, "/run/systemd/journal/socket");
        static const char header[] = "SYSLOG_IDENTIFIER=acrobat-wine\nPRIORITY=3\n"
            "ACROBAT_EVENT=appimage-startup-error\nMESSAGE\n";
        uint64_t size = strlen(message); /* The package architecture is x86_64. */
        struct iovec vectors[] = {
            { .iov_base = (void *)header, .iov_len = sizeof(header) - 1 },
            { .iov_base = &size, .iov_len = sizeof(size) },
            { .iov_base = message, .iov_len = (size_t)size },
            { .iov_base = "\n", .iov_len = 1 }
        };
        struct msghdr entry = { .msg_name = &address, .msg_namelen = sizeof(address),
                               .msg_iov = vectors, .msg_iovlen = 4 };
        (void)sendmsg(fd, &entry, MSG_NOSIGNAL);
        close(fd);
    }
    exit(127);
}

static char *join(const char *a, const char *b)
{
    char *result;
    if (asprintf(&result, "%s/%s", a, b) < 0) fail("allocate path", a);
    return result;
}

static void directory(const char *path)
{
    if (mkdir(path, 0755) && errno != EEXIST) fail("mkdir", path);
}

static void write_mapping(const char *path, const char *value)
{
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) fail("open mapping", path);
    size_t length = strlen(value);
    if (write(fd, value, length) != (ssize_t)length) fail("write mapping", path);
    close(fd);
}

static bool complete_host_closure(const char *appdir)
{
    char *path = join(appdir, "closure.txt");
    FILE *file = fopen(path, "r");
    free(path);
    if (!file) return false;
    char *line = NULL;
    size_t capacity = 0;
    bool complete = true;
    size_t count = 0;
    while (getline(&line, &capacity, file) >= 0) {
        line[strcspn(line, "\r\n")] = '\0';
        if (!*line) continue;
        count++;
        if (strncmp(line, "/nix/store/", 11) || access(line, F_OK)) {
            complete = false;
            break;
        }
    }
    free(line);
    fclose(file);
    return complete && count > 0;
}

static bool dot_entry(const char *name)
{
    return !strcmp(name, ".") || !strcmp(name, "..");
}

static void mirror(const char *source, const char *target, const char *skip)
{
    DIR *dir = opendir(source);
    if (!dir) {
        if (errno == ENOENT) return;
        fail("list directory", source);
    }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (dot_entry(entry->d_name) || (skip && !strcmp(skip, entry->d_name))) continue;
        char *from = join(source, entry->d_name);
        char *to = join(target, entry->d_name);
        struct stat status;
        if (lstat(from, &status)) fail("lstat", from);
        if (S_ISLNK(status.st_mode)) {
            char link[PATH_MAX + 1];
            ssize_t size = readlink(from, link, PATH_MAX);
            if (size < 0) fail("readlink", from);
            link[size] = '\0';
            if (symlink(link, to)) fail("symlink", to);
        } else {
            if (S_ISDIR(status.st_mode)) directory(to);
            else {
                int fd = open(to, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);
                if (fd < 0) fail("create mountpoint", to);
                close(fd);
            }
            if (mount(from, to, NULL, MS_BIND | (S_ISDIR(status.st_mode) ? MS_REC : 0), NULL))
                fail("bind host path", from);
        }
        free(from);
        free(to);
    }
    closedir(dir);
}

static void link_store(const char *source, const char *visible_source, const char *target, bool replace)
{
    DIR *dir = opendir(source);
    if (!dir) {
        if (errno == ENOENT) return;
        fail("list store", source);
    }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (dot_entry(entry->d_name)) continue;
        char *from = join(visible_source, entry->d_name);
        char *to = join(target, entry->d_name);
        if (replace && unlink(to) && errno != ENOENT) fail("replace store link", to);
        if (symlink(from, to)) fail("link store entry", to);
        free(from);
        free(to);
    }
    closedir(dir);
}

int main(int argc, char **argv)
{
    (void)argc;
    char appdir[PATH_MAX], entrypoint[PATH_MAX + 1], cwd[PATH_MAX];
    if (!realpath("/proc/self/exe", appdir)) fail("locate AppRun", "/proc/self/exe");
    char *last = strrchr(appdir, '/');
    if (!last) { errno = EINVAL; fail("locate AppDir", appdir); }
    *last = '\0';
    char *link = join(appdir, "entrypoint");
    ssize_t length = readlink(link, entrypoint, PATH_MAX);
    if (length < 0) fail("read entrypoint", link);
    entrypoint[length] = '\0';
    free(link);
    const char *force = getenv("ACROBAT_APPIMAGE_FORCE_BUNDLE");
    if ((!force || strcmp(force, "1")) && complete_host_closure(appdir)) {
        execv(entrypoint, argv);
        fail("execute host closure", entrypoint);
    }
    if (!getcwd(cwd, sizeof(cwd))) fail("getcwd", "");
    uid_t uid = getuid();
    gid_t gid = getgid();
    if (unshare(CLONE_NEWNS | (uid ? CLONE_NEWUSER : 0))) {
        fprintf(stderr, "Acrobat AppImage: this host must allow unprivileged user namespaces, "
                        "or have the package installed through its Nix flake.\n");
        fail("create private mount namespace", "");
    }
    if (uid) {
        char mapping[80];
        snprintf(mapping, sizeof(mapping), "%u %u 1\n", uid, uid);
        write_mapping("/proc/self/uid_map", mapping);
        write_mapping("/proc/self/setgroups", "deny\n");
        snprintf(mapping, sizeof(mapping), "%u %u 1\n", gid, gid);
        write_mapping("/proc/self/gid_map", mapping);
    }
    if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL)) fail("make mounts private", "/");
    char *root = join(appdir, "mountroot");
    if (mount("tmpfs", root, "tmpfs", 0, "mode=755")) fail("mount temporary root", root);
    mirror("/", root, "nix");
    char *nix = join(root, "nix");
    directory(nix);
    mirror("/nix", nix, "store");
    char *store = join(nix, "store");
    directory(store);
    struct stat host_status;
    if (!stat("/nix/store", &host_status)) {
        char *host = join(nix, ".acrobat-host-store");
        directory(host);
        if (mount("/nix/store", host, NULL, MS_BIND | MS_REC, NULL)) fail("bind host store", host);
        link_store("/nix/store", "/nix/.acrobat-host-store", store, false);
        free(host);
    }
    char *embedded = join(appdir, "nix/store");
    link_store(embedded, embedded, store, true);
    if (chroot(root)) fail("enter temporary root", root);
    if (chdir(cwd)) fail("restore working directory", cwd);
    execv(entrypoint, argv);
    fail("execute embedded closure", entrypoint);
    return 127;
}
