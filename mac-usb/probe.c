#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

static int save(CFPropertyListRef value, const char *path) {
    CFDataRef data = CFPropertyListCreateData(NULL, value, kCFPropertyListXMLFormat_v1_0, 0, NULL);
    if (!data) return -1;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) { CFRelease(data); return -1; }
    const UInt8 *p = CFDataGetBytePtr(data);
    CFIndex left = CFDataGetLength(data);
    int result = 0;
    while (left > 0) {
        ssize_t n = write(fd, p, (size_t)left);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { result = -1; break; }
        p += n; left -= n;
    }
    if (fsync(fd)) result = -1;
    if (close(fd)) result = -1;
    CFRelease(data);
    return result;
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "использование: %s КАТАЛОГ\n", argv[0]); return 2; }
    if (mkdir(argv[1], 0700)) { perror("каталог"); return 1; }
    io_iterator_t iterator = IO_OBJECT_NULL;
    kern_return_t kr = IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBDeviceController"), &iterator);
    if (kr) { fprintf(stderr, "инвентаризация: 0x%x\n", kr); return 1; }
    unsigned count = 0;
    int failed = 0;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        io_string_t registry_path;
        if (IORegistryEntryGetPath(service, kIOServicePlane, registry_path)) { failed = 1; IOObjectRelease(service); continue; }
        CFTypeRef description = IORegistryEntryCreateCFProperty(service, CFSTR("DeviceDescription"), NULL, 0);
        CFTypeRef state = IORegistryEntryCreateCFProperty(service, CFSTR("CurrentState"), NULL, 0);
        if (!description || CFGetTypeID(description) != CFDictionaryGetTypeID()) {
            if (description) CFRelease(description);
            if (state) CFRelease(state);
            IOObjectRelease(service); failed = 1; continue;
        }
        CFMutableDictionaryRef snapshot = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        CFStringRef path_string = CFStringCreateWithCString(NULL, registry_path, kCFStringEncodingUTF8);
        CFDictionarySetValue(snapshot, CFSTR("RegistryPath"), path_string);
        CFDictionarySetValue(snapshot, CFSTR("DeviceDescription"), description);
        if (state) CFDictionarySetValue(snapshot, CFSTR("CurrentState"), state);
        char file[4096];
        int size = snprintf(file, sizeof(file), "%s/controller-%u.plist", argv[1], count);
        if (size < 0 || (size_t)size >= sizeof(file) || save(snapshot, file)) { perror("снимок"); failed = 1; }
        else printf("сохранено %s\nпорт %s\n", file, registry_path);
        ++count;
        CFRelease(path_string); CFRelease(snapshot); CFRelease(description);
        if (state) CFRelease(state);
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    printf("контроллеров: %u\n", count);
    return failed || !count ? 1 : 0;
}
