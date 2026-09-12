#ifndef ASPAN_USB_BRIDGE_H
#define ASPAN_USB_BRIDGE_H

#include <IOKit/IOService.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOCommandGate.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOLocks.h>
#include <kern/kern_types.h>

class aspan_usb_bridge : public IOService {
    OSDeclareDefaultStructors(aspan_usb_bridge);

public:
    virtual bool init(OSDictionary *dictionary = 0) APPLE_KEXT_OVERRIDE;
    virtual void free(void) APPLE_KEXT_OVERRIDE;
    virtual bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
    virtual void stop(IOService *provider) APPLE_KEXT_OVERRIDE;
    virtual IOReturn setProperties(OSObject *properties) APPLE_KEXT_OVERRIDE;

private:
    static IOReturn handlePropertiesGated(OSObject *owner, void *arg0, void *arg1, void *arg2, void *arg3);
    static void leaseFired(OSObject *owner, IOTimerEventSource *sender);
    static void applyThread(void *arg, wait_result_t waitResult);

    IOReturn handlePropertiesGated(OSDictionary *dict);
    IOReturn publishGated(OSDictionary *description, uint32_t lease_ms);
    IOReturn restoreGated(const char *reason);
    IOReturn applyOnKernelThread(OSDictionary *description);
    IOReturn applyConfigurationGated(OSDictionary *description);
    bool pathMatchesGated(const OSString *wanted);
    bool descriptionLooksSafe(OSDictionary *description);

    IOService *m_controller;
    IOWorkLoop *m_workLoop;
    IOCommandGate *m_gate;
    IOTimerEventSource *m_timer;
    IOLock *m_applyLock;
    OSDictionary *m_original;
    bool m_published;
    bool m_applyDone;
    IOReturn m_applyKr;
    uint32_t m_leaseMs;
};

#endif
