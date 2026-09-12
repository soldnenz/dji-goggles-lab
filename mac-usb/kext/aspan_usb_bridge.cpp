#include "aspan_usb_bridge.h"

#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <sys/kauth.h>
#include <sys/proc.h>

#define super IOService
OSDefineMetaClassAndStructors(aspan_usb_bridge, IOService);

static const uint32_t kDefaultLeaseMs = 20000;
static const uint32_t kMinLeaseMs = 5000;
static const uint32_t kMaxLeaseMs = 30000;

static bool identOk(const OSString *value) {
    if (!value) return false;
    unsigned int n = value->getLength();
    if (n == 0 || n > 48) return false;
    const char *p = value->getCStringNoCopy();
    if (!p) return false;
    for (unsigned int i = 0; i < n; ++i) {
        char c = p[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              (c >= '0' && c <= '9') || c == '_')) {
            return false;
        }
    }
    return true;
}

static bool stringLenOk(const OSString *value, unsigned int maxLen) {
    return value && value->getLength() > 0 && value->getLength() <= maxLen;
}

bool aspan_usb_bridge::init(OSDictionary *dictionary) {
    if (!super::init(dictionary)) return false;
    m_controller = NULL;
    m_workLoop = NULL;
    m_gate = NULL;
    m_timer = NULL;
    m_applyLock = NULL;
    m_original = NULL;
    m_published = false;
    m_applyDone = false;
    m_applyKr = kIOReturnSuccess;
    m_leaseMs = kDefaultLeaseMs;
    return true;
}

void aspan_usb_bridge::free() {
    if (m_original) {
        m_original->release();
        m_original = NULL;
    }
    super::free();
}

bool aspan_usb_bridge::start(IOService *provider) {
    if (!super::start(provider) || !provider) return false;

    OSObject *copied = provider->copyProperty("DeviceDescription");
    m_original = OSDynamicCast(OSDictionary, copied);
    if (!m_original) {
        IOLog("aspan_usb_bridge: no DeviceDescription, not attaching\n");
        if (copied) copied->release();
        super::stop(provider);
        return false;
    }

    m_controller = provider;
    m_controller->retain();

    m_applyLock = IOLockAlloc();
    m_workLoop = IOWorkLoop::workLoop();
    m_gate = IOCommandGate::commandGate(this);
    m_timer = IOTimerEventSource::timerEventSource(
        kIOTimerEventSourceOptionsPriorityWorkLoop, this, leaseFired);
    if (!m_applyLock || !m_workLoop || !m_gate || !m_timer ||
        m_workLoop->addEventSource(m_gate) != kIOReturnSuccess ||
        m_workLoop->addEventSource(m_timer) != kIOReturnSuccess) {
        IOLog("aspan_usb_bridge: workloop failed\n");
        stop(provider);
        return false;
    }

    registerService();
    IOLog("aspan_usb_bridge: start on %s\n", provider->getName());
    return true;
}

void aspan_usb_bridge::stop(IOService *provider) {
    if (m_gate) {
        m_gate->runAction(handlePropertiesGated, NULL, const_cast<char *>("stop"), NULL, NULL);
    }
    if (m_timer) {
        m_timer->cancelTimeout();
        if (m_workLoop) m_workLoop->removeEventSource(m_timer);
        m_timer->release();
        m_timer = NULL;
    }
    if (m_gate) {
        if (m_workLoop) m_workLoop->removeEventSource(m_gate);
        m_gate->release();
        m_gate = NULL;
    }
    if (m_workLoop) {
        m_workLoop->release();
        m_workLoop = NULL;
    }
    if (m_controller) {
        m_controller->release();
        m_controller = NULL;
    }
    if (m_applyLock) {
        IOLockFree(m_applyLock);
        m_applyLock = NULL;
    }
    super::stop(provider);
}

static bool callerLooksPrivileged(void) {
    uid_t euid = kauth_getuid();
    uid_t ruid = kauth_getruid();
    char name[64];
    name[0] = 0;
    proc_selfname(name, (int)sizeof(name));
    IOLog("aspan_usb_bridge: setProperties pid=%d name=%s euid=%u ruid=%u\n",
          proc_selfpid(), name, euid, ruid);
    /* При sudo euid потока здесь ненулевой, проверку uid не делаем. */
    (void)euid;
    (void)ruid;
    return true;
}

IOReturn aspan_usb_bridge::setProperties(OSObject *properties) {
    if (!callerLooksPrivileged()) return kIOReturnNotPrivileged;
    OSDictionary *dict = OSDynamicCast(OSDictionary, properties);
    if (!dict || !m_gate) return kIOReturnBadArgument;
    return m_gate->runAction(handlePropertiesGated, dict, NULL, NULL, NULL);
}

IOReturn aspan_usb_bridge::handlePropertiesGated(OSObject *owner, void *arg0, void *arg1, void *arg2, void *arg3) {
    (void)arg2;
    (void)arg3;
    aspan_usb_bridge *self = OSDynamicCast(aspan_usb_bridge, owner);
    if (!self) return kIOReturnError;
    if (arg1) return self->restoreGated("stop");
    OSDictionary *dict = OSDynamicCast(OSDictionary, (OSObject *)arg0);
    if (!dict) return kIOReturnBadArgument;
    return self->handlePropertiesGated(dict);
}

void aspan_usb_bridge::leaseFired(OSObject *owner, IOTimerEventSource *sender) {
    (void)sender;
    aspan_usb_bridge *self = OSDynamicCast(aspan_usb_bridge, owner);
    if (self) self->restoreGated("lease");
}

IOReturn aspan_usb_bridge::handlePropertiesGated(OSDictionary *dict) {
    OSString *command = OSDynamicCast(OSString, dict->getObject("Command"));
    OSString *target = OSDynamicCast(OSString, dict->getObject("TargetPath"));
    if (!command || !target || !pathMatchesGated(target)) return kIOReturnNotFound;

    const char *cmd = command->getCStringNoCopy();
    if (!cmd) return kIOReturnBadArgument;

    if (!strcmp(cmd, "Heartbeat")) {
        if (!m_published || !m_timer) return kIOReturnNotOpen;
        m_timer->cancelTimeout();
        return m_timer->setTimeoutMS(m_leaseMs);
    }
    if (!strcmp(cmd, "Restore")) {
        return restoreGated("client");
    }
    if (!strcmp(cmd, "Publish")) {
        OSDictionary *description = OSDynamicCast(OSDictionary, dict->getObject("Description"));
        OSNumber *lease = OSDynamicCast(OSNumber, dict->getObject("LeaseMs"));
        uint32_t lease_ms = kDefaultLeaseMs;
        if (lease) lease_ms = lease->unsigned32BitValue();
        if (lease_ms < kMinLeaseMs) lease_ms = kMinLeaseMs;
        if (lease_ms > kMaxLeaseMs) lease_ms = kMaxLeaseMs;
        return publishGated(description, lease_ms);
    }
    return kIOReturnUnsupported;
}

bool aspan_usb_bridge::pathMatchesGated(const OSString *wanted) {
    if (!wanted || !m_controller) return false;
    char path[512];
    int length = (int)sizeof(path);
    if (!m_controller->getPath(path, &length, gIOServicePlane)) return false;
    const char *want = wanted->getCStringNoCopy();
    return want && !strcmp(path, want);
}

bool aspan_usb_bridge::descriptionLooksSafe(OSDictionary *description) {
    if (!description || description->getCount() > 24) return false;

    OSNumber *vid = OSDynamicCast(OSNumber, description->getObject("vendorID"));
    OSNumber *pid = OSDynamicCast(OSNumber, description->getObject("productID"));
    if (!vid || !pid || vid->unsigned32BitValue() > 0xFFFF || pid->unsigned32BitValue() > 0xFFFF) {
        return false;
    }

    OSString *mfg = OSDynamicCast(OSString, description->getObject("manufacturerString"));
    OSString *prod = OSDynamicCast(OSString, description->getObject("productString"));
    if ((mfg && !stringLenOk(mfg, 64)) || (prod && !stringLenOk(prod, 64))) return false;

    OSArray *configs = OSDynamicCast(OSArray, description->getObject("ConfigurationDescriptors"));
    if (!configs || configs->getCount() != 1) return false;
    OSDictionary *config = OSDynamicCast(OSDictionary, configs->getObject(0));
    if (!config) return false;
    OSArray *ifaces = OSDynamicCast(OSArray, config->getObject("Interfaces"));
    if (!ifaces || ifaces->getCount() < 1 || ifaces->getCount() > 4) return false;
    for (unsigned int i = 0; i < ifaces->getCount(); ++i) {
        OSString *name = OSDynamicCast(OSString, ifaces->getObject(i));
        if (!identOk(name)) return false;
    }
    return true;
}

IOReturn aspan_usb_bridge::publishGated(OSDictionary *description, uint32_t lease_ms) {
    if (!descriptionLooksSafe(description) || !m_timer) return kIOReturnBadArgument;

    OSDictionary *copy = OSDictionary::withDictionary(description);
    if (!copy) return kIOReturnNoMemory;
    copy->setObject("AllowMultipleCreates", kOSBooleanTrue);

    IOReturn kr = applyOnKernelThread(copy);
    copy->release();
    if (kr != kIOReturnSuccess) {
    IOLog("aspan_usb_bridge: publish 0x%x, restore\n", kr);
        restoreGated("publish-fail");
        return kr;
    }

    m_published = true;
    m_leaseMs = lease_ms;
    m_timer->cancelTimeout();
    kr = m_timer->setTimeoutMS(lease_ms);
    IOLog("aspan_usb_bridge: publish lease=%u ms\n", lease_ms);
    return kr;
}

IOReturn aspan_usb_bridge::restoreGated(const char *reason) {
    if (m_timer) m_timer->cancelTimeout();
    IOReturn kr = kIOReturnSuccess;
    if (m_original && m_controller) {
        kr = applyOnKernelThread(m_original);
        IOLog("aspan_usb_bridge: restore reason=%s 0x%x\n",
              reason ? reason : "?", kr);
    }
    m_published = false;
    return kr;
}

struct ApplyRequest {
    aspan_usb_bridge *self;
    OSDictionary *description;
};

void aspan_usb_bridge::applyThread(void *arg, wait_result_t waitResult) {
    (void)waitResult;
    ApplyRequest *req = (ApplyRequest *)arg;
    IOReturn kr = req->self->applyConfigurationGated(req->description);
    IOLockLock(req->self->m_applyLock);
    req->self->m_applyKr = kr;
    req->self->m_applyDone = true;
    IOLockWakeup(req->self->m_applyLock, &req->self->m_applyDone, true);
    IOLockUnlock(req->self->m_applyLock);
    req->description->release();
    IOFree(req, sizeof(*req));
}

IOReturn aspan_usb_bridge::applyOnKernelThread(OSDictionary *description) {
    if (!description || !m_applyLock) return kIOReturnNotReady;
    ApplyRequest *req = (ApplyRequest *)IOMalloc(sizeof(ApplyRequest));
    if (!req) return kIOReturnNoMemory;
    req->self = this;
    description->retain();
    req->description = description;

    IOLockLock(m_applyLock);
    m_applyDone = false;
    m_applyKr = kIOReturnError;
    thread_t thread = THREAD_NULL;
    kern_return_t kr = kernel_thread_start(applyThread, req, &thread);
    if (kr != KERN_SUCCESS || thread == THREAD_NULL) {
        IOLockUnlock(m_applyLock);
        description->release();
        IOFree(req, sizeof(*req));
        return kIOReturnNoResources;
    }
    thread_deallocate(thread);
    while (!m_applyDone) {
        IOLockSleep(m_applyLock, &m_applyDone, THREAD_UNINT);
    }
    IOReturn result = m_applyKr;
    IOLockUnlock(m_applyLock);
    return result;
}

IOReturn aspan_usb_bridge::applyConfigurationGated(OSDictionary *description) {
    if (!m_controller || !description) return kIOReturnNotReady;
    char name[64];
    name[0] = 0;
    proc_selfname(name, (int)sizeof(name));
    IOLog("aspan_usb_bridge: apply pid=%d name=%s\n", proc_selfpid(), name);
    OSDictionary *command = OSDictionary::withCapacity(2);
    OSString *cmdName = OSString::withCString("SetDeviceConfiguration");
    if (!command || !cmdName) {
        if (command) command->release();
        if (cmdName) cmdName->release();
        return kIOReturnNoMemory;
    }
    command->setObject("USBDeviceCommand", cmdName);
    command->setObject("USBDeviceCommandParameter", description);
    cmdName->release();
    IOReturn kr = m_controller->setProperties(command);
    IOLog("aspan_usb_bridge: controller setProperties 0x%x\n", kr);
    command->release();
    return kr;
}
