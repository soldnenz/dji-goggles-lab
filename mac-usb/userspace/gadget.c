#include "gadget.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

CFMutableDictionaryRef aspan_ncm_description(int vendor, int product, CFStringRef mfg, CFStringRef prod,
                                             const char *const *ifaces, int iface_count) {
    CFMutableArrayRef interfaces = CFArrayCreateMutable(NULL, iface_count, &kCFTypeArrayCallBacks);
    for (int i = 0; i < iface_count; ++i) {
        CFStringRef name = CFStringCreateWithCString(NULL, ifaces[i], kCFStringEncodingUTF8);
        CFArrayAppendValue(interfaces, name);
        CFRelease(name);
    }

    CFMutableDictionaryRef config = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    int attributes = 192;
    int max_power = 0;
    CFNumberRef attr = CFNumberCreate(NULL, kCFNumberIntType, &attributes);
    CFNumberRef power = CFNumberCreate(NULL, kCFNumberIntType, &max_power);
    CFDictionarySetValue(config, CFSTR("Attributes"), attr);
    CFDictionarySetValue(config, CFSTR("MaxPower"), power);
    CFDictionarySetValue(config, CFSTR("Interfaces"), interfaces);
    CFRelease(attr);
    CFRelease(power);
    CFRelease(interfaces);

    CFMutableArrayRef configs = CFArrayCreateMutable(NULL, 1, &kCFTypeArrayCallBacks);
    CFArrayAppendValue(configs, config);
    CFRelease(config);

    CFNumberRef vid = CFNumberCreate(NULL, kCFNumberIntType, &vendor);
    CFNumberRef pid = CFNumberCreate(NULL, kCFNumberIntType, &product);
    CFMutableDictionaryRef desc = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(desc, CFSTR("vendorID"), vid);
    CFDictionarySetValue(desc, CFSTR("productID"), pid);
    CFDictionarySetValue(desc, CFSTR("manufacturerString"), mfg);
    CFDictionarySetValue(desc, CFSTR("productString"), prod);
    CFDictionarySetValue(desc, CFSTR("ConfigurationDescriptors"), configs);
    CFRelease(vid);
    CFRelease(pid);
    CFRelease(configs);
    return desc;
}

CFMutableDictionaryRef aspan_accessory_description(void) {
    const char *ifaces[] = {"AspanUSBData"};
    return aspan_ncm_description(0x18d1, 0x2d00, CFSTR("Google"), CFSTR("Android Accessory"), ifaces, 1);
}

CFMutableDictionaryRef aspan_stock_description(void) {
    const char *ifaces[] = {
        "AppleUSBNCMControl", "AppleUSBNCMData", "AppleUSBNCMControlAux", "AppleUSBNCMDataAux"
    };
    return aspan_ncm_description(0x05ac, 0x1905, CFSTR("Apple Inc."), CFSTR("Mac"), ifaces, 4);
}

char *aspan_controller_path(const char *drd) {
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBDeviceController"), &iterator)) {
        return NULL;
    }
    char *found = NULL;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        io_string_t path;
        if (!IORegistryEntryGetPath(service, kIOServicePlane, path) && strstr(path, drd)) {
            found = strdup(path);
            IOObjectRelease(service);
            break;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return found;
}

io_service_t aspan_find_bridge(const char *drd) {
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("aspan_usb_bridge"), &iterator)) {
        return IO_OBJECT_NULL;
    }
    io_service_t service, match = IO_OBJECT_NULL;
    while ((service = IOIteratorNext(iterator))) {
        io_string_t path;
        if (!IORegistryEntryGetPath(service, kIOServicePlane, path) && strstr(path, drd)) {
            match = service;
            break;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return match;
}

IOReturn aspan_send(io_service_t bridge, CFStringRef command, const char *target_path,
                    CFDictionaryRef description, int lease_ms) {
    CFMutableDictionaryRef dict = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(dict, CFSTR("Command"), command);
    CFStringRef path = CFStringCreateWithCString(NULL, target_path, kCFStringEncodingUTF8);
    CFDictionarySetValue(dict, CFSTR("TargetPath"), path);
    CFRelease(path);
    if (description) CFDictionarySetValue(dict, CFSTR("Description"), description);
    if (lease_ms > 0) {
        CFNumberRef lease = CFNumberCreate(NULL, kCFNumberIntType, &lease_ms);
        CFDictionarySetValue(dict, CFSTR("LeaseMs"), lease);
        CFRelease(lease);
    }
    IOReturn kr = IORegistryEntrySetCFProperties(bridge, dict);
    CFRelease(dict);
    return kr;
}

IOReturn aspan_publish_accessory(io_service_t bridge, const char *target_path, int lease_ms) {
    CFDictionaryRef desc = aspan_accessory_description();
    IOReturn kr = aspan_send(bridge, CFSTR("Publish"), target_path, desc, lease_ms);
    CFRelease(desc);
    return kr;
}

IOReturn aspan_publish_stock(io_service_t bridge, const char *target_path) {
    CFDictionaryRef desc = aspan_stock_description();
    IOReturn kr = aspan_send(bridge, CFSTR("Publish"), target_path, desc, 5000);
    CFRelease(desc);
    return kr;
}
