#ifndef ASPAN_GADGET_H
#define ASPAN_GADGET_H

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>

CFMutableDictionaryRef aspan_ncm_description(int vendor, int product, CFStringRef mfg, CFStringRef prod,
                                             const char *const *ifaces, int iface_count);
CFMutableDictionaryRef aspan_accessory_description(void);
CFMutableDictionaryRef aspan_stock_description(void);
char *aspan_controller_path(const char *drd);
io_service_t aspan_find_bridge(const char *drd);
IOReturn aspan_send(io_service_t bridge, CFStringRef command, const char *target_path,
                    CFDictionaryRef description, int lease_ms);
IOReturn aspan_publish_accessory(io_service_t bridge, const char *target_path, int lease_ms);
IOReturn aspan_publish_stock(io_service_t bridge, const char *target_path);

#endif
