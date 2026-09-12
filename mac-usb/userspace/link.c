#include "gadget.h"

#include <mach/mach.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Селекторы IOUSBDeviceInterfaceUserClient, тип 123. */
enum {
    kUCType = 123,
    kUCOpen = 0,
    kUCClose = 1,
    kUCSetClass = 3,
    kUCSetSubclass = 4,
    kUCSetProtocol = 5,
    kUCCreatePipe = 10,
    kUCCommit = 11,
    kUCWrite = 14,
    kUCCreateData = 18,
    kUCReleaseData = 19
};

enum {
    kEpBulk = 2,
    kEpOut = 0,
    kEpIn = 1
};

#define CH_SQUIRREL 0x5749
#define CH_VIDEO    0x574A
#define CH_PI       0x7530

static volatile sig_atomic_t g_stop;
static uint8_t g_rx[2 * 1024 * 1024];
static size_t g_rx_len;
static FILE *g_h264;
static FILE *g_rxdump;
static int g_play_fd = -1;
static pid_t g_play_pid = -1;
static int g_video_frames;
static int g_sps;
static uint64_t g_video_bytes;
static uint64_t g_rx_bytes;
static int g_ctrl_frames;
static double g_last_video_s;

static void on_stop(int sig) {
    (void)sig;
    g_stop = 1;
}

static double now_s(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (double)tv.tv_sec + tv.tv_usec / 1e6;
}

static uint8_t crc8(const uint8_t *data, size_t n) {
    uint8_t value = 0x77;
    for (size_t i = 0; i < n; ++i) {
        value ^= data[i];
        for (int b = 0; b < 8; ++b) {
            value = (uint8_t)((value >> 1) ^ ((value & 1) ? 0x8C : 0));
        }
    }
    return value;
}

static uint16_t crc16(const uint8_t *data, size_t n) {
    uint16_t value = 0x3692;
    for (size_t i = 0; i < n; ++i) {
        value ^= data[i];
        for (int b = 0; b < 8; ++b) {
            value = (uint16_t)((value >> 1) ^ ((value & 1) ? 0x8408 : 0));
        }
    }
    return value;
}

static size_t wrap_duml(uint16_t channel, const uint8_t *duml, size_t duml_len, uint8_t *out, size_t cap) {
    size_t total = 8 + duml_len;
    if (cap < total) return 0;
    out[0] = 0x55;
    out[1] = 0xCC;
    out[2] = (uint8_t)(channel & 0xFF);
    out[3] = (uint8_t)(channel >> 8);
    uint32_t plen = (uint32_t)duml_len;
    memcpy(out + 4, &plen, 4);
    memcpy(out + 8, duml, duml_len);
    return total;
}

static size_t build_duml(uint8_t sender, uint8_t receiver, uint16_t seq, uint8_t flags,
                         uint8_t cmd_set, uint8_t cmd_id, const uint8_t *payload, size_t plen,
                         uint8_t *out, size_t cap) {
    size_t duml_len = 13 + plen;
    if (cap < duml_len) return 0;
    uint16_t ver_len = (uint16_t)((1u << 10) | duml_len);
    out[0] = 0x55;
    out[1] = (uint8_t)(ver_len & 0xFF);
    out[2] = (uint8_t)(ver_len >> 8);
    out[3] = crc8(out, 3);
    out[4] = sender;
    out[5] = receiver;
    out[6] = (uint8_t)(seq & 0xFF);
    out[7] = (uint8_t)(seq >> 8);
    out[8] = flags;
    out[9] = cmd_set;
    out[10] = cmd_id;
    if (plen) memcpy(out + 11, payload, plen);
    uint16_t c16 = crc16(out, duml_len - 2);
    out[duml_len - 2] = (uint8_t)(c16 & 0xFF);
    out[duml_len - 1] = (uint8_t)(c16 >> 8);
    return duml_len;
}

static size_t build_squirrel(uint16_t seq, uint8_t *out, size_t cap) {
    static const uint8_t payload[] = {
        0x17, 0x00, 0x00, 0x23, 0x00,
        'S', 'Q', 'U', 'I', 'R', 'R', 'E', 'L', 0x02
    };
    uint8_t duml[64];
    size_t n = build_duml(0x02, 0x3C, seq, 0x40, 0x00, 0x88, payload, sizeof(payload), duml, sizeof(duml));
    return wrap_duml(CH_SQUIRREL, duml, n, out, cap);
}

static size_t build_pi_088(uint16_t seq, uint8_t *out, size_t cap) {
    static const uint8_t payload[] = {
        0x17, 0x00, 0x00, 0x23, 0x00, 0x41, 0x50, 0x50, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02
    };
    uint8_t duml[64];
    size_t n = build_duml(0x02, 0x3C, seq, 0x40, 0x00, 0x88, payload, sizeof(payload), duml, sizeof(duml));
    return wrap_duml(CH_PI, duml, n, out, cap);
}

static size_t build_pi_099(uint16_t seq, uint8_t counter, uint8_t *out, size_t cap) {
    uint8_t payload[32];
    static const uint8_t base[] = {
        0x02, 0x02, 0x00, 0x00, 0xd5, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x13, 0x00, 0x0d, 0x00,
        0x63, 0x61, 0x6d, 0x63, 0x61, 0x70, 0x5f, 0x63, 0x6f, 0x6d, 0x6d, 0x6f, 0x6e, 0x00, 0x00, 0x00, 0x00
    };
    memcpy(payload, base, sizeof(base));
    payload[4] = (uint8_t)(0xD5 + counter);
    uint8_t duml[80];
    /* receiver_type=8, idx=1 → 0x28 */
    size_t n = build_duml(0x02, 0x28, seq, 0x40, 0x00, 0x99, payload, sizeof(base), duml, sizeof(duml));
    return wrap_duml(CH_PI, duml, n, out, cap);
}

static io_service_t find_function(const char *drd, const char *function) {
    CFMutableDictionaryRef match = IOServiceMatching("IOUSBDeviceInterface");
    CFMutableDictionaryRef props = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFStringRef fn = CFStringCreateWithCString(NULL, function, kCFStringEncodingUTF8);
    CFDictionarySetValue(props, CFSTR("USBDeviceFunction"), fn);
    CFDictionarySetValue(match, CFSTR("IOPropertyMatch"), props);
    CFRelease(fn);
    CFRelease(props);

    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, match, &iterator)) {
        return IO_OBJECT_NULL;
    }
    io_service_t service, found = IO_OBJECT_NULL;
    while ((service = IOIteratorNext(iterator))) {
        io_string_t path;
        if (!IORegistryEntryGetPath(service, kIOServicePlane, path) && strstr(path, drd)) {
            found = service;
            break;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return found;
}

static kern_return_t scalar(io_connect_t conn, uint32_t sel, uint64_t *args, uint32_t n,
                            uint64_t *out, uint32_t *nout) {
    return IOConnectCallScalarMethod(conn, sel, args, n, out, nout);
}

static void stop_player(void) {
    if (g_play_fd >= 0) {
        close(g_play_fd);
        g_play_fd = -1;
    }
    if (g_play_pid > 0) {
        kill(g_play_pid, SIGTERM);
        for (int i = 0; i < 30; ++i) {
            if (waitpid(g_play_pid, NULL, WNOHANG) == g_play_pid) {
                g_play_pid = -1;
                return;
            }
            usleep(10000);
        }
        kill(g_play_pid, SIGKILL);
        waitpid(g_play_pid, NULL, 0);
        g_play_pid = -1;
    }
}

static void start_player(void) {
    if (g_play_fd >= 0) return;
    int fds[2];
    if (pipe(fds) != 0) return;
    pid_t pid = fork();
    if (pid == 0) {
        dup2(fds[0], 0);
        close(fds[0]);
        close(fds[1]);
        execl("/opt/homebrew/bin/ffplay", "ffplay",
              "-hide_banner", "-loglevel", "warning",
              "-fflags", "nobuffer", "-flags", "low_delay", "-framedrop",
              "-window_title", "aspan goggles",
              "-f", "h264", "-i", "pipe:0", (char *)NULL);
        _exit(127);
    }
    close(fds[0]);
    if (pid < 0) {
        close(fds[1]);
        return;
    }
    g_play_fd = fds[1];
    g_play_pid = pid;
    printf("ffplay pid=%d fd=%d\n", pid, g_play_fd);
}

static int has_sps(const uint8_t *p, size_t n) {
    for (size_t i = 0; i + 4 < n; ++i) {
        if (p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 0 && p[i + 3] == 1 && (p[i + 4] & 0x1F) == 7) return 1;
        if (p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 1 && (p[i + 3] & 0x1F) == 7) return 1;
    }
    return 0;
}

static void emit_video(const uint8_t *p, size_t n) {
    g_video_frames++;
    g_video_bytes += n;
    if (g_h264) fwrite(p, 1, n, g_h264);
    if (!g_sps && has_sps(p, n)) {
        g_sps = 1;
        printf("SPS/PPS, запускаю ffplay, video_bytes=%llu\n", (unsigned long long)g_video_bytes);
        start_player();
    } else if (g_sps && g_play_fd < 0) {
        start_player();
    }
    g_last_video_s = now_s();
    if (g_play_fd >= 0) {
        ssize_t w = write(g_play_fd, p, n);
        if (w < 0) stop_player();
    }
}

static int maybe_reply_088(const uint8_t *duml, size_t n, uint8_t *out, size_t cap) {
    if (n < 13) return 0;
    if (duml[9] != 0x00 || duml[10] != 0x88) return 0;
    if ((duml[8] & 0x80) != 0) return 0;
    const uint8_t *pl = duml + 11;
    size_t plen = n - 13;
    if (plen < 2 || pl[0] != 0x19) return 0;
    static const uint8_t body[] = {0x1a, 0x00, 0x00, 0x00};
    uint16_t seq = (uint16_t)(duml[6] | (duml[7] << 8));
    uint8_t built[32];
    size_t dn = build_duml(duml[5], duml[4], seq, 0x80, 0x00, 0x88, body, sizeof(body), built, sizeof(built));
    return (int)wrap_duml(CH_SQUIRREL, built, dn, out, cap);
}

static void handle_frames(uint8_t *reply, size_t *reply_len, size_t reply_cap) {
    *reply_len = 0;
    while (g_rx_len >= 8) {
        size_t start = 0;
        int found = 0;
        for (size_t i = 0; i + 1 < g_rx_len; ++i) {
            if (g_rx[i] == 0x55 && g_rx[i + 1] == 0xCC) {
                start = i;
                found = 1;
                break;
            }
        }
        if (!found) {
            g_rx_len = 0;
            return;
        }
        if (start) {
            memmove(g_rx, g_rx + start, g_rx_len - start);
            g_rx_len -= start;
        }
        if (g_rx_len < 8) return;
        uint32_t plen = 0;
        memcpy(&plen, g_rx + 4, 4);
        if (plen == 0 || plen > 2 * 1024 * 1024) {
            memmove(g_rx, g_rx + 1, g_rx_len - 1);
            g_rx_len -= 1;
            continue;
        }
        size_t total = 8 + plen;
        if (g_rx_len < total) return;
        uint16_t ch = (uint16_t)(g_rx[2] | (g_rx[3] << 8));
        const uint8_t *payload = g_rx + 8;
        if (ch == CH_VIDEO || ch == 0x574A) {
            emit_video(payload, plen);
        } else {
            g_ctrl_frames++;
            uint8_t cmd_set = (plen >= 11) ? payload[9] : 0;
            uint8_t cmd_id = (plen >= 11) ? payload[10] : 0;
            printf("ctrl ch=0x%04x n=%u cmd=%02x:%02x\n", ch, plen, cmd_set, cmd_id);
            uint8_t tmp[64];
            int rn = maybe_reply_088(payload, plen, tmp, sizeof(tmp));
            if (rn > 0 && *reply_len == 0 && (size_t)rn <= reply_cap) {
                memcpy(reply, tmp, (size_t)rn);
                *reply_len = (size_t)rn;
            }
        }
        memmove(g_rx, g_rx + total, g_rx_len - total);
        g_rx_len -= total;
    }
}

static uint32_t probe_read_sel(io_connect_t conn, uint64_t pipe, uint64_t token) {
    static const uint32_t cands[] = {13, 12, 15, 16, 17, 9};
    uint64_t args[8];
    uint64_t output[8];
    for (size_t i = 0; i < sizeof(cands) / sizeof(cands[0]); ++i) {
        uint32_t nout = 1;
        memset(output, 0, sizeof(output));
        args[0] = pipe;
        args[1] = token;
        args[2] = 512;
        args[3] = 30;
        kern_return_t sret = scalar(conn, cands[i], args, 4, output, &nout);
        printf("probe read sel=%u 0x%x out=%llx\n", cands[i], sret, output[0]);
        if (sret == 0 || sret == (kern_return_t)0xE00002D6) return cands[i];
    }
    return 0;
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    const char *controller = "usb-drd0";
    int seconds = 45;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--controller") && i + 1 < argc) controller = argv[++i];
        else if (!strcmp(argv[i], "--seconds") && i + 1 < argc) seconds = atoi(argv[++i]);
        else {
            fprintf(stderr, "использование: %s [--controller usb-drd0] [--seconds 45]\n", argv[0]);
            return 2;
        }
    }
    if (geteuid() != 0) {
        fprintf(stderr, "нужен root\n");
        return 1;
    }

    char *target = aspan_controller_path(controller);
    io_service_t bridge = aspan_find_bridge(controller);
    if (!target || !bridge) {
        fprintf(stderr, "нет контроллера/kext для %s\n", controller);
        free(target);
        if (bridge) IOObjectRelease(bridge);
        return 1;
    }
    printf("target %s\n", target);

    IOReturn kr = aspan_publish_accessory(bridge, target, 20000);
    printf("publish accessory 0x%x\n", kr);
    if (kr) {
        aspan_publish_stock(bridge, target);
        IOObjectRelease(bridge);
        free(target);
        return 1;
    }

    io_service_t iface = IO_OBJECT_NULL;
    for (int i = 0; i < 40 && !iface; ++i) {
        iface = find_function(controller, "AspanUSBData");
        if (!iface) usleep(250000);
    }
    if (!iface) {
        printf("нет AspanUSBData на %s\n", controller);
        aspan_publish_stock(bridge, target);
        IOObjectRelease(bridge);
        free(target);
        return 1;
    }
    io_string_t ipath;
    IORegistryEntryGetPath(iface, kIOServicePlane, ipath);
    printf("iface %s\n", ipath);

    io_connect_t conn = IO_OBJECT_NULL;
    kern_return_t sret = IOServiceOpen(iface, mach_task_self(), kUCType, &conn);
    printf("IOServiceOpen type=%d 0x%x\n", kUCType, sret);
    IOObjectRelease(iface);
    if (sret || !conn) {
        aspan_publish_stock(bridge, target);
        IOObjectRelease(bridge);
        free(target);
        return 1;
    }

    uint64_t args[8] = {0};
    uint64_t output[8] = {0};
    uint32_t nout = 0;
    sret = scalar(conn, kUCOpen, args, 1, output, &nout);
    printf("open 0x%x\n", sret);

    args[0] = 0xFF;
    args[1] = 0;
    nout = 0;
    scalar(conn, kUCSetClass, args, 2, output, &nout);
    args[0] = 0xFF;
    scalar(conn, kUCSetSubclass, args, 2, output, &nout);
    args[0] = 0;
    scalar(conn, kUCSetProtocol, args, 2, output, &nout);

    nout = 1;
    args[0] = kEpBulk;
    args[1] = kEpOut;
    args[2] = 512;
    args[3] = 0;
    args[4] = 0;
    args[5] = 0;
    sret = scalar(conn, kUCCreatePipe, args, 6, output, &nout);
    printf("pipe out 0x%x id=%llx\n", sret, output[0]);
    uint64_t pipe_out = output[0];

    nout = 1;
    args[0] = kEpBulk;
    args[1] = kEpIn;
    args[2] = 512;
    args[3] = 0;
    args[4] = 0;
    args[5] = 0;
    sret = scalar(conn, kUCCreatePipe, args, 6, output, &nout);
    printf("pipe in 0x%x id=%llx\n", sret, output[0]);
    uint64_t pipe_in = output[0];

    nout = 0;
    sret = scalar(conn, kUCCommit, args, 0, output, &nout);
    printf("commit 0x%x\n", sret);

    nout = 3;
    args[0] = 0x1000;
    sret = scalar(conn, kUCCreateData, args, 1, output, &nout);
    void *writeptr = (void *)(uintptr_t)output[0];
    uint64_t write_token = output[2];
    printf("writeBuf 0x%x ptr=%llx token=%llx\n", sret, output[0], write_token);

    nout = 3;
    args[0] = 0x10000;
    sret = scalar(conn, kUCCreateData, args, 1, output, &nout);
    void *readptr = (void *)(uintptr_t)output[0];
    uint64_t read_cap = output[1];
    uint64_t read_token = output[2];
    printf("readBuf 0x%x ptr=%llx cap=%llx token=%llx\n", sret, output[0], read_cap, read_token);

    g_h264 = fopen("/tmp/aspan-goggles.h264", "wb");
    g_rxdump = fopen("/tmp/aspan-usb-rx.bin", "wb");

    signal(SIGINT, on_stop);
    signal(SIGTERM, on_stop);
    signal(SIGPIPE, SIG_IGN);
    uint16_t seq = (uint16_t)(time(NULL) & 0xFFFF);
    int writes = 0, write_ok = 0, reads_ok = 0;
    uint32_t read_sel = 0;
    int probed = 0;
    int pi_mode = 0;
    uint8_t magic_counter = 0;
    double t0 = now_s();
    double last_hb = 0;
    double last_write = 0;
    double end = t0 + seconds;

    while (!g_stop && now_s() < end) {
        double t = now_s();
        if (t - last_hb >= 5) {
            IOReturn hb = aspan_send(bridge, CFSTR("Heartbeat"), target, NULL, 0);
            if (hb) printf("heartbeat 0x%x\n", hb);
            last_hb = t;
        }

        if (g_play_pid > 0 && g_last_video_s > 0 && t - g_last_video_s > 1.5) {
            printf("видео пропало, закрываю плеер\n");
            stop_player();
        }

        if (write_ok && !probed && readptr) {
            read_sel = probe_read_sel(conn, pipe_out, read_token);
            printf("using read sel=%u\n", read_sel);
            probed = 1;
        }

        if (read_sel && readptr) {
            for (int i = 0; i < 32; ++i) {
                uint32_t on = 1;
                memset(output, 0, sizeof(output));
                args[0] = pipe_out;
                args[1] = read_token;
                args[2] = read_cap ? read_cap : 512;
                if (args[2] > 0x10000) args[2] = 0x10000;
                args[3] = 20;
                sret = scalar(conn, read_sel, args, 4, output, &on);
                if (sret == 0 && output[0] > 0 && output[0] <= 0x10000) {
                    size_t got = (size_t)output[0];
                    reads_ok++;
                    g_rx_bytes += got;
                    if (g_rxdump) fwrite(readptr, 1, got, g_rxdump);
                    if (g_rx_len + got > sizeof(g_rx)) g_rx_len = 0;
                    memcpy(g_rx + g_rx_len, readptr, got);
                    g_rx_len += got;
                    uint8_t reply[128];
                    size_t rlen = 0;
                    handle_frames(reply, &rlen, sizeof(reply));
                    if (rlen && writeptr) {
                        memcpy(writeptr, reply, rlen);
                        uint32_t wn = 1;
                        args[0] = pipe_in;
                        args[1] = write_token;
                        args[2] = rlen;
                        args[3] = 100;
                        scalar(conn, kUCWrite, args, 4, output, &wn);
                        printf("replied 00:88 n=%zu\n", rlen);
                    }
                } else if (sret && sret != (kern_return_t)0xE00002D6) {
                    break;
                } else {
                    break;
                }
            }
        }

        if (t - last_write >= 1.0 && writeptr) {
            if (!pi_mode && t - t0 > 12 && g_rx_bytes == 0) {
                pi_mode = 1;
                printf("нет RX 12с, keepalive Pi 0x7530\n");
            }
            uint8_t pkt[160];
            size_t n = 0;
            if (pi_mode) {
                n = build_pi_099(seq++, magic_counter++, pkt, sizeof(pkt));
                memcpy(writeptr, pkt, n);
                nout = 1;
                args[0] = pipe_in;
                args[1] = write_token;
                args[2] = n;
                args[3] = 200;
                sret = scalar(conn, kUCWrite, args, 4, output, &nout);
                writes++;
                if (sret == 0) write_ok++;
                usleep(50000);
                n = build_pi_088(seq++, pkt, sizeof(pkt));
            } else {
                n = build_squirrel(seq++, pkt, sizeof(pkt));
            }
            memcpy(writeptr, pkt, n);
            nout = 1;
            args[0] = pipe_in;
            args[1] = write_token;
            args[2] = n;
            args[3] = 200;
            sret = scalar(conn, kUCWrite, args, 4, output, &nout);
            writes++;
            if (sret == 0) write_ok++;
            if (writes <= 3 || (writes % 5) == 0) {
                printf("write 0x%x n=%zu rx_bytes=%llu video_frames=%d ctrl=%d\n",
                       sret, n, (unsigned long long)g_rx_bytes, g_video_frames, g_ctrl_frames);
            }
            last_write = t;
        }
        usleep(2000);
    }

    if (write_token) {
        nout = 0;
        args[0] = write_token;
        scalar(conn, kUCReleaseData, args, 1, output, &nout);
    }
    if (read_token) {
        nout = 0;
        args[0] = read_token;
        scalar(conn, kUCReleaseData, args, 1, output, &nout);
    }
    nout = 0;
    scalar(conn, kUCClose, NULL, 0, output, &nout);
    IOServiceClose(conn);
    if (g_h264) fclose(g_h264);
    if (g_rxdump) fclose(g_rxdump);
    stop_player();

    kr = aspan_publish_stock(bridge, target);
    printf("stock 0x%x writes=%d ok=%d reads_ok=%d rx=%llu video_frames=%d sps=%d ctrl=%d\n",
           kr, writes, write_ok, reads_ok, (unsigned long long)g_rx_bytes, g_video_frames, g_sps, g_ctrl_frames);
    IOObjectRelease(bridge);
    free(target);
    return (g_sps || g_video_bytes > 0) ? 0 : 2;
}
