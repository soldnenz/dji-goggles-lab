#include "g3lv.h"

#include <stdio.h>
#include <string.h>

#ifdef USE_LIBUSB
#include <libusb.h>
#endif

static int g_claimed;
static char g_detail[160] = "MI04 off";

#ifdef USE_LIBUSB
static libusb_context *g_ctx;
static libusb_device_handle *g_h;
static uint8_t g_out_ep;

#define DJI_VID 0x2CA3
#define DJI_PID 0x0020
#define MI04_IFACE 4
#endif

int g3_mi04_claimed(void)
{
    return g_claimed;
}

const char *g3_mi04_detail(void)
{
    return g_detail;
}

int g3_mi04_open(char *err, size_t errlen)
{
#ifndef USE_LIBUSB
    snprintf(g_detail, sizeof g_detail, "built without libusb");
    if (err && errlen)
        snprintf(err, errlen, "%s", g_detail);
    return -1;
#else
    if (g_claimed)
        return 0;
    int rc = libusb_init(&g_ctx);
    if (rc) {
        snprintf(g_detail, sizeof g_detail, "libusb_init %d", rc);
        if (err && errlen)
            snprintf(err, errlen, "%s", g_detail);
        return -1;
    }
    g_h = libusb_open_device_with_vid_pid(g_ctx, DJI_VID, DJI_PID);
    if (!g_h) {
        snprintf(g_detail, sizeof g_detail, "no 2ca3:0020");
        if (err && errlen)
            snprintf(err, errlen, "%s", g_detail);
        libusb_exit(g_ctx);
        g_ctx = NULL;
        return -1;
    }
    if (libusb_kernel_driver_active(g_h, MI04_IFACE) == 1)
        libusb_detach_kernel_driver(g_h, MI04_IFACE);
    rc = libusb_claim_interface(g_h, MI04_IFACE);
    if (rc) {
        snprintf(g_detail, sizeof g_detail, "claim MI04: %s", libusb_strerror(rc));
        if (err && errlen)
            snprintf(err, errlen, "%s", g_detail);
        libusb_close(g_h);
        g_h = NULL;
        libusb_exit(g_ctx);
        g_ctx = NULL;
        return -1;
    }
    struct libusb_config_descriptor *cfg = NULL;
    rc = libusb_get_active_config_descriptor(libusb_get_device(g_h), &cfg);
    if (rc || !cfg) {
        snprintf(g_detail, sizeof g_detail, "no active config");
        libusb_release_interface(g_h, MI04_IFACE);
        libusb_close(g_h);
        g_h = NULL;
        libusb_exit(g_ctx);
        g_ctx = NULL;
        if (err && errlen)
            snprintf(err, errlen, "%s", g_detail);
        return -1;
    }
    g_out_ep = 0;
    for (int i = 0; i < cfg->bNumInterfaces; i++) {
        const struct libusb_interface *itf = &cfg->interface[i];
        if (!itf->altsetting || itf->altsetting[0].bInterfaceNumber != MI04_IFACE)
            continue;
        const struct libusb_interface_descriptor *d = &itf->altsetting[0];
        for (int e = 0; e < d->bNumEndpoints; e++) {
            uint8_t addr = d->endpoint[e].bEndpointAddress;
            if ((addr & 0x80) == 0)
                g_out_ep = addr;
        }
    }
    libusb_free_config_descriptor(cfg);
    if (!g_out_ep) {
        snprintf(g_detail, sizeof g_detail, "no bulk OUT on MI04");
        libusb_release_interface(g_h, MI04_IFACE);
        libusb_close(g_h);
        g_h = NULL;
        libusb_exit(g_ctx);
        g_ctx = NULL;
        if (err && errlen)
            snprintf(err, errlen, "%s", g_detail);
        return -1;
    }
    g_claimed = 1;
    snprintf(g_detail, sizeof g_detail, "MI04 2ca3:0020 out=0x%02x", g_out_ep);
    return 0;
#endif
}

int g3_mi04_write(const uint8_t *p, size_t n)
{
#ifdef USE_LIBUSB
    if (!g_claimed || !g_h)
        return 0;
    int xfer = 0;
    int rc = libusb_bulk_transfer(g_h, g_out_ep, (unsigned char *)p, (int)n, &xfer, 250);
    return rc == 0 && xfer == (int)n;
#else
    (void)p;
    (void)n;
    return 0;
#endif
}

void g3_mi04_close(void)
{
#ifdef USE_LIBUSB
    if (g_h) {
        if (g_claimed)
            libusb_release_interface(g_h, MI04_IFACE);
        libusb_close(g_h);
        g_h = NULL;
    }
    if (g_ctx) {
        libusb_exit(g_ctx);
        g_ctx = NULL;
    }
#endif
    g_claimed = 0;
    snprintf(g_detail, sizeof g_detail, "MI04 closed");
}
