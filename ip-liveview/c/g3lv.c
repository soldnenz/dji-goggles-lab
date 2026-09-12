#define _GNU_SOURCE
#include "g3lv.h"

#include <arpa/inet.h>
#include <errno.h>
#include <ifaddrs.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#ifndef MSG_DONTWAIT
#define MSG_DONTWAIT 0
#endif

static volatile sig_atomic_t g_stop;

static void on_sig(int sig)
{
    (void)sig;
    g_stop = 1;
}

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + ts.tv_nsec / 1e9;
}

static int has_ipv4(const char *want)
{
    struct ifaddrs *ifa = NULL, *p;
    if (getifaddrs(&ifa) != 0)
        return 0;
    int hit = 0;
    for (p = ifa; p; p = p->ifa_next) {
        if (!p->ifa_addr || p->ifa_addr->sa_family != AF_INET)
            continue;
        char buf[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &((struct sockaddr_in *)p->ifa_addr)->sin_addr, buf, sizeof buf);
        if (strcmp(buf, want) == 0)
            hit = 1;
    }
    freeifaddrs(ifa);
    return hit;
}

static int sendto_ok(int fd, const uint8_t *p, size_t n, const struct sockaddr_in *to)
{
    ssize_t w = sendto(fd, p, n, 0, (const struct sockaddr *)to, sizeof *to);
    if (w < 0) {
        if (errno == EADDRNOTAVAIL || errno == ENETUNREACH || errno == EHOSTUNREACH || errno == EINVAL)
            return 0;
        return -1;
    }
    return 1;
}

static void fill_addr(struct sockaddr_in *a, const char *ip, uint16_t port)
{
    memset(a, 0, sizeof *a);
    a->sin_family = AF_INET;
    a->sin_port = htons(port);
    inet_pton(AF_INET, ip, &a->sin_addr);
}

typedef struct {
    const char *out_path;
    const char *bind_ip;
    const char *peer_ip;
    int wifi;
    int wired;
    int rtx;
    int boost;
    int verbose;
    int ack_every;
    uint16_t session;
    int session_set;
    uint16_t local_port;
    uint32_t boost_kbps;
    double boost_interval;
    double handshake_interval;
    double ack_interval;
    double video_timeout;
} Opt;

static void usage(const char *argv0)
{
    fprintf(stderr,
            "usage: %s [--wifi|--wired] [--out live.h264] [--bind IP] [--peer IP]\n"
            "          [--no-rtx] [--boost] [--boost-kbps 22500] [-v]\n"
            "Goggles 3 UDP liveview :9003. Writes Annex-B. Decode is your problem.\n",
            argv0);
}

static int parse_opt(int argc, char **argv, Opt *o)
{
    memset(o, 0, sizeof *o);
    o->out_path = "live.h264";
    o->rtx = 1;
    o->boost_kbps = G3_BOOST_KBPS;
    o->boost_interval = 0.25;
    o->handshake_interval = 1.0;
    o->ack_interval = 1.0 / 30.0;
    o->video_timeout = 1.0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--wifi") == 0)
            o->wifi = 1;
        else if (strcmp(argv[i], "--wired") == 0)
            o->wired = 1;
        else if (strcmp(argv[i], "--no-rtx") == 0)
            o->rtx = 0;
        else if (strcmp(argv[i], "--boost") == 0)
            o->boost = 1;
        else if (strcmp(argv[i], "--no-boost") == 0)
            o->boost = 0;
        else if (strcmp(argv[i], "--ack-every") == 0)
            o->ack_every = 1;
        else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0)
            o->verbose = 1;
        else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 2;
        } else if (strcmp(argv[i], "--out") == 0 && i + 1 < argc)
            o->out_path = argv[++i];
        else if (strcmp(argv[i], "--bind") == 0 && i + 1 < argc)
            o->bind_ip = argv[++i];
        else if (strcmp(argv[i], "--peer") == 0 && i + 1 < argc)
            o->peer_ip = argv[++i];
        else if (strcmp(argv[i], "--session") == 0 && i + 1 < argc) {
            o->session = (uint16_t)strtoul(argv[++i], NULL, 0);
            o->session_set = 1;
        } else if (strcmp(argv[i], "--local-port") == 0 && i + 1 < argc)
            o->local_port = (uint16_t)atoi(argv[++i]);
        else if (strcmp(argv[i], "--boost-kbps") == 0 && i + 1 < argc)
            o->boost_kbps = (uint32_t)atoi(argv[++i]);
        else if (strcmp(argv[i], "--boost-interval") == 0 && i + 1 < argc)
            o->boost_interval = atof(argv[++i]);
        else {
            fprintf(stderr, "unknown arg %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    Opt opt;
    int pr = parse_opt(argc, argv, &opt);
    if (pr)
        return pr == 2 ? 0 : pr;

    signal(SIGINT, on_sig);
    signal(SIGTERM, on_sig);

    uint16_t session = opt.session;
    if (!opt.session_set) {
        FILE *ur = fopen("/dev/urandom", "rb");
        if (!ur || fread(&session, 1, sizeof session, ur) != sizeof session)
            session = (uint16_t)(time(NULL) ^ (getpid() << 8));
        if (ur)
            fclose(ur);
        session = (uint16_t)(session | 1);
    }
    uint8_t hs[48];
    g3_build_handshake(hs, session);
    uint16_t seed = g3_handshake_seed(hs);

    G3Loss rtx;
    G3Frame asmbl;
    g3_loss_init(&rtx, seed);
    g3_frame_init(&asmbl);

    struct sockaddr_in peers[2];
    const char *pnames[2];
    int npeers = 0;
    if (opt.peer_ip) {
        fill_addr(&peers[0], opt.peer_ip, 9003);
        pnames[0] = "manual";
        npeers = 1;
    } else {
        int wifi = opt.wifi || (!opt.wifi && !opt.wired);
        int wired = opt.wired || (!opt.wifi && !opt.wired);
        if (wifi) {
            fill_addr(&peers[npeers], "192.168.2.1", 9003);
            pnames[npeers++] = "wifi";
        }
        if (wired) {
            fill_addr(&peers[npeers], "192.168.60.2", 9003);
            pnames[npeers++] = "wired";
        }
    }

    const char *bind_ip = opt.bind_ip;
    if (!bind_ip)
        bind_ip = has_ipv4("192.168.60.1") ? "192.168.60.1" : "0.0.0.0";

    FILE *out = NULL;
    if (strcmp(opt.out_path, "-") == 0)
        out = stdout;
    else {
        out = fopen(opt.out_path, "wb");
        if (!out) {
            perror(opt.out_path);
            return 1;
        }
        setvbuf(out, NULL, _IOFBF, 1 << 20);
    }

    int fd = -1;
    int linked = 0, joined = 0;
    struct sockaddr_in link_addr, join_addr;
    memset(&link_addr, 0, sizeof link_addr);
    memset(&join_addr, 0, sizeof join_addr);

    double last_hs = 0, last_video = 0, last_ctrl = 0, last_ack = 0, last_stats = 0;
    double last_boost = 0, last_mi04 = 0;
    uint16_t boost_seq = 0, type5_seq = seed;
    uint8_t type5_counter = 1;
    uint16_t type5_win_s = seed, type5_win_e = seed;
    uint64_t bytes_w = 0;
    int frames_w = 0;
    const char *boost_via = "off";
    int mi04_fail_logged = 0;
    uint8_t boost_duml[64];
    size_t boost_dlen = 0;
    uint8_t pkt[2048];
    uint8_t rx[65536];

    fprintf(stderr, "[*] g3lv session=0x%04x seed=0x%04x bind=%s rtx=%d boost=%d\n",
            session, seed, bind_ip, opt.rtx, opt.boost);

    while (!g_stop) {
        if (fd < 0) {
            fd = socket(AF_INET, SOCK_DGRAM, 0);
            if (fd < 0) {
                perror("socket");
                break;
            }
            int one = 1;
            setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
            int rbuf = 4 * 1024 * 1024;
            setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rbuf, sizeof rbuf);
            struct sockaddr_in loc;
            fill_addr(&loc, bind_ip, opt.local_port);
            if (bind(fd, (struct sockaddr *)&loc, sizeof loc) != 0) {
                perror("bind");
                close(fd);
                fd = -1;
                usleep(400000);
                continue;
            }
            last_hs = 0;
        }

        double t = now_s();
        int ctrl_alive = linked && (t - last_ctrl) <= opt.video_timeout;
        int video_alive = joined && (t - last_video) <= opt.video_timeout;
        if (joined && !video_alive) {
            joined = 0;
            g3_loss_reset(&rtx);
            g3_frame_clear(&asmbl);
            g3_frame_init(&asmbl);
            fprintf(stderr, "[*] stalled\n");
        }
        if (linked && !ctrl_alive) {
            linked = 0;
            fprintf(stderr, "[*] idle\n");
        }

        if (t - last_stats >= 1.0) {
            double dt = t - last_stats;
            if (dt < 0.001)
                dt = 0.001;
            double fps = frames_w / dt;
            double kbps = bytes_w * 8.0 / dt / 1000.0;
            fprintf(stderr, "[*] %s fps=%.1f %.0f kbps frames=%d rtx=%u boost=%s\n",
                    video_alive ? "live" : (ctrl_alive ? "telemetry" : "idle"),
                    fps, kbps, asmbl.complete, rtx.requests, boost_via);
            frames_w = 0;
            bytes_w = 0;
            last_stats = t;
        }

        uint16_t resend[G3_MAX_RESEND];
        int nresend = 0;
        if (video_alive && opt.rtx)
            nresend = g3_loss_missing(&rtx, resend, G3_MAX_RESEND);
        uint16_t ack_s = rtx.armed ? rtx.start : seed;
        uint16_t ack_e = rtx.armed ? rtx.end : seed;

        if (opt.boost && !g3_mi04_claimed() && t - last_mi04 >= 2.0) {
            last_mi04 = t;
            char err[160];
            if (g3_mi04_open(err, sizeof err) == 0)
                fprintf(stderr, "[*] %s\n", g3_mi04_detail());
            else if (!mi04_fail_logged) {
                fprintf(stderr, "[*] boost USB: %s; UDP type-5\n", err);
                mi04_fail_logged = 1;
            }
        }

        boost_dlen = 0;
        if (opt.boost && t - last_boost >= opt.boost_interval) {
            size_t bl = g3_build_bitrate_boost(boost_duml, sizeof boost_duml, boost_seq, opt.boost_kbps);
            if (g3_mi04_claimed() && g3_mi04_write(boost_duml, bl)) {
                boost_via = "mi04";
                boost_seq = (uint16_t)((boost_seq + 1) & 0xffff);
                last_boost = t;
            } else if (linked) {
                boost_dlen = bl;
                boost_seq = (uint16_t)((boost_seq + 1) & 0xffff);
                type5_seq = (uint16_t)((type5_seq + 8) & 0xffff);
                type5_win_s = seed;
                type5_win_e = type5_seq;
                size_t n5 = g3_build_type5(pkt, sizeof pkt, session, type5_seq, seed, type5_seq,
                                           boost_duml, boost_dlen, type5_counter);
                if (sendto_ok(fd, pkt, n5, &link_addr) <= 0) {
                    close(fd);
                    fd = -1;
                    linked = joined = 0;
                    continue;
                }
                type5_counter = (uint8_t)((type5_counter + 1) & 0xff);
                boost_via = "udp";
                last_boost = t;
                boost_dlen = 0;
            }
        }

        if (linked && t - last_ack >= opt.ack_interval) {
            size_t n = g3_build_ack(pkt, sizeof pkt, session, ack_s, ack_e, resend, nresend,
                                    seed, seed, type5_win_s, type5_win_e, boost_duml, boost_dlen);
            boost_dlen = 0;
            if (sendto_ok(fd, pkt, n, &link_addr) <= 0) {
                close(fd);
                fd = -1;
                linked = joined = 0;
                continue;
            }
            last_ack = t;
        }

        if (!video_alive && !ctrl_alive && t - last_hs >= opt.handshake_interval) {
            int ok = 1;
            for (int i = 0; i < npeers; i++) {
                int s = sendto_ok(fd, hs, 48, &peers[i]);
                if (s <= 0) {
                    ok = 0;
                    break;
                }
                if (opt.verbose)
                    fprintf(stderr, "[*] handshake %s\n", pnames[i]);
            }
            last_hs = t;
            if (!ok) {
                close(fd);
                fd = -1;
                continue;
            }
        }

        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int pret = poll(&pfd, 1, 20);
        if (pret < 0) {
            if (errno == EINTR)
                continue;
            close(fd);
            fd = -1;
            continue;
        }
        if (pret == 0)
            continue;

        for (int burst = 0; burst < 64; burst++) {
            struct sockaddr_in from;
            socklen_t flen = sizeof from;
            ssize_t n = recvfrom(fd, rx, sizeof rx, MSG_DONTWAIT, (struct sockaddr *)&from, &flen);
            if (n < 0)
                break;
            G3Header hdr;
            if (!g3_parse_header(rx, (size_t)n, &hdr))
                continue;
            t = now_s();
            if (hdr.type == G3_TYPE_HANDSHAKE) {
                linked = 1;
                link_addr = from;
                last_ctrl = t;
                size_t an = g3_build_ack(pkt, sizeof pkt, session, seed, seed, NULL, 0,
                                         seed, seed, seed, seed, NULL, 0);
                sendto_ok(fd, pkt, an, &from);
                last_ack = t;
                if (opt.verbose)
                    fprintf(stderr, "[*] telemetry peer %s\n", inet_ntoa(from.sin_addr));
                continue;
            }
            if (g3_is_data(rx, (size_t)n)) {
                if (!linked) {
                    linked = 1;
                    link_addr = from;
                }
                last_ctrl = t;
                size_t an = g3_build_ack(pkt, sizeof pkt, session, ack_s, ack_e,
                                         opt.rtx ? resend : NULL, opt.rtx ? nresend : 0,
                                         seed, seed, type5_win_s, type5_win_e, boost_duml, boost_dlen);
                boost_dlen = 0;
                sendto_ok(fd, pkt, an, &from);
                last_ack = t;
                continue;
            }
            G3Video vid;
            if (!g3_parse_video(rx, (size_t)n, &vid))
                continue;
            uint16_t gaps[G3_MAX_RESEND];
            int ngaps = opt.rtx ? g3_loss_push(&rtx, vid.hdr.seq, gaps, G3_MAX_RESEND) : 0;
            if (!joined) {
                joined = linked = 1;
                join_addr = link_addr = from;
                fprintf(stderr, "[*] live %s\n", inet_ntoa(from.sin_addr));
            } else if (join_addr.sin_addr.s_addr != from.sin_addr.s_addr)
                continue;
            last_video = last_ctrl = t;
            int last_part = vid.part == vid.n_parts - 1;
            uint16_t win_s = rtx.armed ? rtx.start : seed;
            uint16_t win_e = rtx.armed ? rtx.end : seed;
            if (last_part || opt.ack_every || ngaps) {
                size_t an = g3_build_ack(pkt, sizeof pkt, session, win_s, win_e, gaps, ngaps,
                                         seed, seed, type5_win_s, type5_win_e, boost_duml, boost_dlen);
                boost_dlen = 0;
                sendto_ok(fd, pkt, an, &join_addr);
                last_ack = t;
            }
            size_t au_len = 0;
            uint8_t *au = g3_frame_push(&asmbl, &vid, &au_len);
            if (!au)
                continue;
            frames_w++;
            bytes_w += au_len;
            if (out)
                fwrite(au, 1, au_len, out);
            if (opt.verbose)
                fprintf(stderr, "frame %u parts=%u bytes=%zu seq=%u\n",
                        vid.frame, vid.n_parts, au_len, vid.hdr.seq);
            free(au);
        }
    }

    g3_mi04_close();
    g3_frame_clear(&asmbl);
    if (fd >= 0)
        close(fd);
    if (out && out != stdout)
        fclose(out);
    fprintf(stderr, "[*] stop\n");
    return 0;
}
