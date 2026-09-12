#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t g_stop;

static void on_stop(int sig) {
    (void)sig;
    g_stop = 1;
}

static int path_contains(const char *path, const char *needle) {
    return path && needle && strstr(path, needle) != NULL;
}

static unsigned child_count(io_registry_entry_t entry) {
    io_iterator_t iterator = IO_OBJECT_NULL;
    unsigned count = 0;
    if (IORegistryEntryGetChildIterator(entry, kIOServicePlane, &iterator)) return 0;
    io_object_t child;
    while ((child = IOIteratorNext(iterator))) {
        ++count;
        IOObjectRelease(child);
    }
    IOObjectRelease(iterator);
    return count;
}

static void print_controllers(void) {
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBDeviceController"), &iterator)) {
        printf("controller_error=нет\n");
        return;
    }
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        io_string_t registry_path;
        if (IORegistryEntryGetPath(service, kIOServicePlane, registry_path)) {
            IOObjectRelease(service);
            continue;
        }
        const char *drd = path_contains(registry_path, "usb-drd0") ? "usb-drd0" :
                          path_contains(registry_path, "usb-drd1") ? "usb-drd1" : "usb-drd?";
        CFTypeRef state = IORegistryEntryCreateCFProperty(service, CFSTR("CurrentState"), NULL, 0);
        const char *device_state = "?";
        int on_bus = -1;
        long speed = -1;
        if (state && CFGetTypeID(state) == CFDictionaryGetTypeID()) {
            CFStringRef ds = CFDictionaryGetValue((CFDictionaryRef)state, CFSTR("DeviceState"));
            CFBooleanRef bus = CFDictionaryGetValue((CFDictionaryRef)state, CFSTR("OnBus"));
            CFNumberRef sp = CFDictionaryGetValue((CFDictionaryRef)state, CFSTR("ConnectionSpeed"));
            static char buf[64];
            if (ds && CFGetTypeID(ds) == CFStringGetTypeID() &&
                CFStringGetCString(ds, buf, sizeof(buf), kCFStringEncodingUTF8)) {
                device_state = buf;
            }
            if (bus && CFGetTypeID(bus) == CFBooleanGetTypeID()) on_bus = CFBooleanGetValue(bus);
            if (sp && CFGetTypeID(sp) == CFNumberGetTypeID()) CFNumberGetValue(sp, kCFNumberLongType, &speed);
        }
        printf("device %s state=%s on_bus=%d speed=%ld path=%s\n",
               drd, device_state, on_bus, speed, registry_path);
        if (state) CFRelease(state);
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
}

static void print_host_ports(const char *class_name) {
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching(class_name), &iterator)) return;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        io_string_t registry_path;
        if (IORegistryEntryGetPath(service, kIOServicePlane, registry_path)) {
            IOObjectRelease(service);
            continue;
        }
        if (!path_contains(registry_path, "usb-drd0") && !path_contains(registry_path, "usb-drd1")) {
            IOObjectRelease(service);
            continue;
        }
        const char *drd = path_contains(registry_path, "usb-drd0") ? "usb-drd0" : "usb-drd1";
        unsigned n = child_count(service);
        printf("host %s class=%s children=%u path=%s\n", drd, class_name, n, registry_path);
        if (n) {
            io_iterator_t kids = IO_OBJECT_NULL;
            if (!IORegistryEntryGetChildIterator(service, kIOServicePlane, &kids)) {
                io_object_t child;
                while ((child = IOIteratorNext(kids))) {
                    io_name_t name;
                    io_string_t child_path;
                    if (!IORegistryEntryGetName(child, name)) {
                        if (!IORegistryEntryGetPath(child, kIOServicePlane, child_path))
                            printf("host-child %s name=%s path=%s\n", drd, name, child_path);
                        else
                            printf("host-child %s name=%s\n", drd, name);
                    }
                    IOObjectRelease(child);
                }
                IOObjectRelease(kids);
            }
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
}

static void sample(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    printf("--- t=%ld.%03ld ---\n",
           (long)ts.tv_sec, ts.tv_nsec / 1000000L);
    print_controllers();
    print_host_ports("AppleUSB20XHCIARMPort");
    print_host_ports("AppleUSB30XHCIARMPort");
    fflush(stdout);
}

int main(int argc, char **argv) {
    int once = 0;
    if (argc == 2 && !strcmp(argv[1], "--once")) once = 1;
    else if (argc != 1) {
        fprintf(stderr, "использование: %s [--once]\n", argv[0]);
        return 2;
    }
    signal(SIGINT, on_stop);
    signal(SIGTERM, on_stop);
    sample();
    if (once) return 0;
    printf("ждём кабель в один порт, Ctrl-C выход\n");
    fflush(stdout);
    while (!g_stop) {
        usleep(500000);
        if (!g_stop) sample();
    }
    return 0;
}
