#include "gadget.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t g_stop;

static void on_stop(int sig) {
    (void)sig;
    g_stop = 1;
}

static void usage(const char *argv0) {
    fprintf(stderr,
            "usage:\n"
            "  %s --dry-run --controller usb-drd0|usb-drd1\n"
            "  %s --restore --controller usb-drd0|usb-drd1\n"
            "  %s --publish-accessory --controller usb-drd0|usb-drd1 [--lease-ms 20000]\n"
            "  %s --publish-stock --controller usb-drd0|usb-drd1\n",
            argv0, argv0, argv0, argv0);
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    const char *controller = NULL;
    int dry_run = 0, restore = 0, publish = 0, stock = 0, lease_ms = 20000;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--dry-run")) dry_run = 1;
        else if (!strcmp(argv[i], "--restore")) restore = 1;
        else if (!strcmp(argv[i], "--publish-accessory")) publish = 1;
        else if (!strcmp(argv[i], "--publish-stock")) { publish = 1; stock = 1; }
        else if (!strcmp(argv[i], "--controller") && i + 1 < argc) controller = argv[++i];
        else if (!strcmp(argv[i], "--lease-ms") && i + 1 < argc) lease_ms = atoi(argv[++i]);
        else {
            usage(argv[0]);
            return 2;
        }
    }
    if (!controller || (!dry_run && !restore && !publish) || (publish && restore)) {
        usage(argv[0]);
        return 2;
    }
    if (strcmp(controller, "usb-drd0") && strcmp(controller, "usb-drd1")) {
        fprintf(stderr, "controller: usb-drd0 or usb-drd1\n");
        return 2;
    }

    char *target = aspan_controller_path(controller);
    if (!target) {
        fprintf(stderr, "controller %s not found\n", controller);
        return 1;
    }
    printf("target %s\n", target);

    if (dry_run) {
        CFDictionaryRef desc = aspan_accessory_description();
        CFDataRef xml = CFPropertyListCreateData(NULL, desc, kCFPropertyListXMLFormat_v1_0, 0, NULL);
        if (xml) {
            fwrite(CFDataGetBytePtr(xml), 1, (size_t)CFDataGetLength(xml), stdout);
            CFRelease(xml);
        }
        CFRelease(desc);
        free(target);
        return 0;
    }

    if (geteuid() != 0) {
        fprintf(stderr, "need root\n");
        free(target);
        return 1;
    }

    io_service_t bridge = aspan_find_bridge(controller);
    if (!bridge) {
        fprintf(stderr, "aspan_usb_bridge not loaded for %s\n", controller);
        free(target);
        return 1;
    }

    if (restore || stock) {
        IOReturn kr = aspan_publish_stock(bridge, target);
        printf("stock 0x%x\n", kr);
        IOObjectRelease(bridge);
        free(target);
        return kr ? 1 : 0;
    }

    IOReturn kr = aspan_publish_accessory(bridge, target, lease_ms);
    printf("publish 0x%x lease_ms=%d\n", kr, lease_ms);
    if (kr) {
        IOObjectRelease(bridge);
        free(target);
        return 1;
    }

    signal(SIGINT, on_stop);
    signal(SIGTERM, on_stop);
    while (!g_stop) {
        usleep(5000000);
        if (g_stop) break;
        kr = aspan_send(bridge, CFSTR("Heartbeat"), target, NULL, 0);
        if (kr) {
            printf("heartbeat 0x%x\n", kr);
            break;
        }
    }
    kr = aspan_publish_stock(bridge, target);
    printf("stock 0x%x\n", kr);
    IOObjectRelease(bridge);
    free(target);
    return kr ? 1 : 0;
}
