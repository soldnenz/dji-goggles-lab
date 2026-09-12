#include "g3lv.h"

#include <stdlib.h>
#include <string.h>

static const uint8_t kCrc8[256] = {
    0x00, 0x5e, 0xbc, 0xe2, 0x61, 0x3f, 0xdd, 0x83, 0xc2, 0x9c, 0x7e, 0x20, 0xa3, 0xfd, 0x1f, 0x41,
    0x9d, 0xc3, 0x21, 0x7f, 0xfc, 0xa2, 0x40, 0x1e, 0x5f, 0x01, 0xe3, 0xbd, 0x3e, 0x60, 0x82, 0xdc,
    0x23, 0x7d, 0x9f, 0xc1, 0x42, 0x1c, 0xfe, 0xa0, 0xe1, 0xbf, 0x5d, 0x03, 0x80, 0xde, 0x3c, 0x62,
    0xbe, 0xe0, 0x02, 0x5c, 0xdf, 0x81, 0x63, 0x3d, 0x7c, 0x22, 0xc0, 0x9e, 0x1d, 0x43, 0xa1, 0xff,
    0x46, 0x18, 0xfa, 0xa4, 0x27, 0x79, 0x9b, 0xc5, 0x84, 0xda, 0x38, 0x66, 0xe5, 0xbb, 0x59, 0x07,
    0xdb, 0x85, 0x67, 0x39, 0xba, 0xe4, 0x06, 0x58, 0x19, 0x47, 0xa5, 0xfb, 0x78, 0x26, 0xc4, 0x9a,
    0x65, 0x3b, 0xd9, 0x87, 0x04, 0x5a, 0xb8, 0xe6, 0xa7, 0xf9, 0x1b, 0x45, 0xc6, 0x98, 0x7a, 0x24,
    0xf8, 0xa6, 0x44, 0x1a, 0x99, 0xc7, 0x25, 0x7b, 0x3a, 0x64, 0x86, 0xd8, 0x5b, 0x05, 0xe7, 0xb9,
    0x8c, 0xd2, 0x30, 0x6e, 0xed, 0xb3, 0x51, 0x0f, 0x4e, 0x10, 0xf2, 0xac, 0x2f, 0x71, 0x93, 0xcd,
    0x11, 0x4f, 0xad, 0xf3, 0x70, 0x2e, 0xcc, 0x92, 0xd3, 0x8d, 0x6f, 0x31, 0xb2, 0xec, 0x0e, 0x50,
    0xaf, 0xf1, 0x13, 0x4d, 0xce, 0x90, 0x72, 0x2c, 0x6d, 0x33, 0xd1, 0x8f, 0x0c, 0x52, 0xb0, 0xee,
    0x32, 0x6c, 0x8e, 0xd0, 0x53, 0x0d, 0xef, 0xb1, 0xf0, 0xae, 0x4c, 0x12, 0x91, 0xcf, 0x2d, 0x73,
    0xca, 0x94, 0x76, 0x28, 0xab, 0xf5, 0x17, 0x49, 0x08, 0x56, 0xb4, 0xea, 0x69, 0x37, 0xd5, 0x8b,
    0x57, 0x09, 0xeb, 0xb5, 0x36, 0x68, 0x8a, 0xd4, 0x95, 0xcb, 0x29, 0x77, 0xf4, 0xaa, 0x48, 0x16,
    0xe9, 0xb7, 0x55, 0x0b, 0x88, 0xd6, 0x34, 0x6a, 0x2b, 0x75, 0x97, 0xc9, 0x4a, 0x14, 0xf6, 0xa8,
    0x74, 0x2a, 0xc8, 0x96, 0x15, 0x4b, 0xa9, 0xf7, 0xb6, 0xe8, 0x0a, 0x54, 0xd7, 0x89, 0x6b, 0x35
};

static const uint16_t kCrc16[256] = {
    0x0000, 0x1189, 0x2312, 0x329b, 0x4624, 0x57ad, 0x6536, 0x74bf,
    0x8c48, 0x9dc1, 0xaf5a, 0xbed3, 0xca6c, 0xdbe5, 0xe97e, 0xf8f7,
    0x1081, 0x0108, 0x3393, 0x221a, 0x56a5, 0x472c, 0x75b7, 0x643e,
    0x9cc9, 0x8d40, 0xbfdb, 0xae52, 0xdaed, 0xcb64, 0xf9ff, 0xe876,
    0x2102, 0x308b, 0x0210, 0x1399, 0x6726, 0x76af, 0x4434, 0x55bd,
    0xad4a, 0xbcc3, 0x8e58, 0x9fd1, 0xeb6e, 0xfae7, 0xc87c, 0xd9f5,
    0x3183, 0x200a, 0x1291, 0x0318, 0x77a7, 0x662e, 0x54b5, 0x453c,
    0xbdcb, 0xac42, 0x9ed9, 0x8f50, 0xfbef, 0xea66, 0xd8fd, 0xc974,
    0x4204, 0x538d, 0x6116, 0x709f, 0x0420, 0x15a9, 0x2732, 0x36bb,
    0xce4c, 0xdfc5, 0xed5e, 0xfcd7, 0x8868, 0x99e1, 0xab7a, 0xbaf3,
    0x5285, 0x430c, 0x7197, 0x601e, 0x14a1, 0x0528, 0x37b3, 0x263a,
    0xdecd, 0xcf44, 0xfddf, 0xec56, 0x98e9, 0x8960, 0xbbfb, 0xaa72,
    0x6306, 0x728f, 0x4014, 0x519d, 0x2522, 0x34ab, 0x0630, 0x17b9,
    0xef4e, 0xfec7, 0xcc5c, 0xddd5, 0xa96a, 0xb8e3, 0x8a78, 0x9bf1,
    0x7387, 0x620e, 0x5095, 0x411c, 0x35a3, 0x242a, 0x16b1, 0x0738,
    0xffcf, 0xee46, 0xdcdd, 0xcd54, 0xb9eb, 0xa862, 0x9af9, 0x8b70,
    0x8408, 0x9581, 0xa71a, 0xb693, 0xc22c, 0xd3a5, 0xe13e, 0xf0b7,
    0x0840, 0x19c9, 0x2b52, 0x3adb, 0x4e64, 0x5fed, 0x6d76, 0x7cff,
    0x9489, 0x8500, 0xb79b, 0xa612, 0xd2ad, 0xc324, 0xf1bf, 0xe036,
    0x18c1, 0x0948, 0x3bd3, 0x2a5a, 0x5ee5, 0x4f6c, 0x7df7, 0x6c7e,
    0xa50a, 0xb483, 0x8618, 0x9791, 0xe32e, 0xf2a7, 0xc03c, 0xd1b5,
    0x2942, 0x38cb, 0x0a50, 0x1bd9, 0x6f66, 0x7eef, 0x4c74, 0x5dfd,
    0xb58b, 0xa402, 0x9699, 0x8710, 0xf3af, 0xe226, 0xd0bd, 0xc134,
    0x39c3, 0x284a, 0x1ad1, 0x0b58, 0x7fe7, 0x6e6e, 0x5cf5, 0x4d7c,
    0xc60c, 0xd785, 0xe51e, 0xf497, 0x8028, 0x91a1, 0xa33a, 0xb2b3,
    0x4a44, 0x5bcd, 0x6956, 0x78df, 0x0c60, 0x1de9, 0x2f72, 0x3efb,
    0xd68d, 0xc704, 0xf59f, 0xe416, 0x90a9, 0x8120, 0xb3bb, 0xa232,
    0x5ac5, 0x4b4c, 0x79d7, 0x685e, 0x1ce1, 0x0d68, 0x3ff3, 0x2e7a,
    0xe70e, 0xf687, 0xc41c, 0xd595, 0xa12a, 0xb0a3, 0x8238, 0x93b1,
    0x6b46, 0x7acf, 0x4854, 0x59dd, 0x2d62, 0x3ceb, 0x0e70, 0x1ff9,
    0xf78f, 0xe606, 0xd49d, 0xc514, 0xb1ab, 0xa022, 0x92b9, 0x8330,
    0x7bc7, 0x6a4e, 0x58d5, 0x495c, 0x3de3, 0x2c6a, 0x1ef1, 0x0f78
};

static const uint8_t kHandshake[48] = {
    0x30, 0x80, 0x3a, 0xdd, 0x00, 0x00, 0x00, 0x57,
    0xd0, 0xe9, 0x64, 0x00, 0x64, 0x00, 0xc0, 0x05,
    0x14, 0x00, 0x00, 0x0a, 0x00, 0x64, 0x00, 0x64,
    0x00, 0xc0, 0x05, 0x14, 0x00, 0x00, 0x64, 0x00,
    0x14, 0x00, 0x64, 0x00, 0xc0, 0x05, 0x14, 0x00,
    0x00, 0x64, 0x00, 0x01, 0x01, 0x04, 0x0a, 0x02
};

static const uint8_t kBoostHead[19] = {
    0xeb, 0xfe, 0xef, 0xbe, 0x03, 0x00, 0x0f, 0x00, 0x02, 0x01,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00
};

void g3_put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xff);
    p[1] = (uint8_t)(v >> 8);
}

uint16_t g3_get16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

uint8_t g3_xor7(const uint8_t *p)
{
    return (uint8_t)(p[0] ^ p[1] ^ p[2] ^ p[3] ^ p[4] ^ p[5] ^ p[6]);
}

uint16_t g3_seq_ahead(uint16_t newer, uint16_t older)
{
    return (uint16_t)((newer - older) & G3_SEQ_MASK);
}

static uint8_t duml_crc8(const uint8_t *p, size_t n)
{
    uint8_t v = 0x77;
    for (size_t i = 0; i < n; i++)
        v = kCrc8[(p[i] ^ v) & 0xff];
    return v;
}

static uint16_t duml_crc16(const uint8_t *p, size_t n)
{
    uint16_t v = 0x3692;
    for (size_t i = 0; i < n; i++)
        v = (uint16_t)((v >> 8) ^ kCrc16[(p[i] ^ v) & 0xff]);
    return v;
}

int g3_parse_header(const uint8_t *p, size_t n, G3Header *out)
{
    if (n < G3_HDR)
        return 0;
    uint16_t flagged = g3_get16(p);
    uint16_t length = (uint16_t)(flagged & 0x7fff);
    if (p[7] != g3_xor7(p) || length != n)
        return 0;
    out->length = length;
    out->session = g3_get16(p + 2);
    out->seq = g3_get16(p + 4);
    out->type = p[6];
    return 1;
}

size_t g3_pack_header(uint8_t *out, uint16_t length, uint16_t session, uint16_t seq, uint8_t type)
{
    g3_put16(out, (uint16_t)((length & 0x7fff) | G3_FLAG));
    g3_put16(out + 2, session);
    g3_put16(out + 4, seq);
    out[6] = type;
    out[7] = g3_xor7(out);
    return G3_HDR;
}

size_t g3_build_handshake(uint8_t *out, uint16_t session)
{
    memcpy(out, kHandshake, 48);
    g3_put16(out + 2, session);
    g3_put16(out, (uint16_t)((48 & 0x7fff) | G3_FLAG));
    out[7] = g3_xor7(out);
    return 48;
}

uint16_t g3_handshake_seed(const uint8_t *pkt)
{
    return g3_get16(pkt + 8);
}

size_t g3_build_duml(uint8_t *out, size_t cap, uint8_t sender, uint8_t receiver, uint16_t seq,
                     uint8_t cmdset, uint8_t cmd, const uint8_t *payload, size_t plen)
{
    size_t length = 13 + plen;
    if (cap < length)
        return 0;
    memset(out, 0, length);
    out[0] = 0x55;
    g3_put16(out + 1, (uint16_t)((1u << 10) | (length & 0x3ff)));
    out[4] = sender;
    out[5] = receiver;
    g3_put16(out + 6, seq);
    out[8] = 0;
    out[9] = cmdset;
    out[10] = cmd;
    out[3] = duml_crc8(out, 3);
    if (plen)
        memcpy(out + 11, payload, plen);
    g3_put16(out + (int)length - 2, duml_crc16(out, length - 2));
    return length;
}

size_t g3_build_bitrate_boost(uint8_t *out, size_t cap, uint16_t seq, uint32_t kbps)
{
    uint8_t payload[23];
    memcpy(payload, kBoostHead, 19);
    payload[19] = (uint8_t)(kbps);
    payload[20] = (uint8_t)(kbps >> 8);
    payload[21] = (uint8_t)(kbps >> 16);
    payload[22] = (uint8_t)(kbps >> 24);
    return g3_build_duml(out, cap, G3_BOOST_SENDER, G3_BOOST_RECEIVER, seq,
                         G3_BOOST_CMDSET, G3_BOOST_CMD, payload, sizeof payload);
}

size_t g3_build_type5(uint8_t *out, size_t cap, uint16_t session, uint16_t seq,
                      uint16_t win_s, uint16_t win_e, const uint8_t *duml, size_t dlen, uint8_t counter)
{
    size_t body = 12 + dlen;
    size_t n = G3_HDR + body;
    if (cap < n)
        return 0;
    g3_pack_header(out, (uint16_t)n, session, seq, G3_TYPE_CMD);
    g3_put16(out + 8, win_s);
    g3_put16(out + 10, win_e);
    g3_put16(out + 12, 0);
    g3_put16(out + 14, 0);
    out[16] = counter;
    out[17] = 0x01;
    out[18] = 0x00;
    out[19] = 0x00;
    if (dlen)
        memcpy(out + 20, duml, dlen);
    g3_put16(out, (uint16_t)((n & 0x7fff) | G3_FLAG));
    out[7] = g3_xor7(out);
    return n;
}

size_t g3_build_ack(uint8_t *out, size_t cap, uint16_t session, uint16_t win_s, uint16_t win_e,
                    const uint16_t *resend, int nresend, uint16_t t3s, uint16_t t3e,
                    uint16_t t5s, uint16_t t5e, const uint8_t *duml, size_t dlen)
{
    if (nresend < 0)
        nresend = 0;
    size_t body = 4 + 2 + (size_t)nresend * 2 + 6 + 10 + dlen;
    size_t n = G3_HDR + body;
    if (cap < n)
        return 0;
    g3_pack_header(out, (uint16_t)n, session, 0, G3_TYPE_ACK);
    uint8_t *b = out + G3_HDR;
    g3_put16(b, win_s);
    g3_put16(b + 2, win_e);
    g3_put16(b + 4, (uint16_t)nresend);
    b += 6;
    for (int i = 0; i < nresend; i++, b += 2)
        g3_put16(b, resend[i]);
    g3_put16(b, t3s);
    g3_put16(b + 2, t3e);
    g3_put16(b + 4, 0);
    g3_put16(b + 6, t5s);
    g3_put16(b + 8, t5e);
    g3_put16(b + 10, 0);
    g3_put16(b + 12, 0);
    g3_put16(b + 14, (uint16_t)dlen);
    if (dlen)
        memcpy(b + 16, duml, dlen);
    g3_put16(out, (uint16_t)((n & 0x7fff) | G3_FLAG));
    out[7] = g3_xor7(out);
    return n;
}

int g3_parse_video(const uint8_t *p, size_t n, G3Video *out)
{
    G3Header hdr;
    if (!g3_parse_header(p, n, &hdr) || hdr.type != G3_TYPE_VIDEO || n < G3_VIDEO_OFF)
        return 0;
    out->hdr = hdr;
    out->win_start = g3_get16(p + 8);
    out->win_end = g3_get16(p + 10);
    out->frame = p[0x10];
    out->n_parts = (uint8_t)(p[0x11] & 0x7f);
    out->part = (uint8_t)((p[0x11] >> 7) | ((p[0x12] & 0x1f) << 1));
    out->h264 = p + G3_VIDEO_OFF;
    out->h264_len = n - G3_VIDEO_OFF;
    return 1;
}

int g3_is_data(const uint8_t *p, size_t n)
{
    G3Header hdr;
    return g3_parse_header(p, n, &hdr) && hdr.type == G3_TYPE_DATA && n >= 12;
}

static int have_get(const G3Loss *w, uint16_t seq)
{
    return (w->have[seq >> 3] >> (seq & 7)) & 1;
}

static void have_set(G3Loss *w, uint16_t seq)
{
    w->have[seq >> 3] |= (uint8_t)(1u << (seq & 7));
}

static void have_clr(G3Loss *w, uint16_t seq)
{
    w->have[seq >> 3] &= (uint8_t)~(1u << (seq & 7));
}

void g3_loss_init(G3Loss *w, uint16_t seed)
{
    memset(w, 0, sizeof *w);
    w->seed = seed;
    w->start = seed;
    w->end = seed;
}

void g3_loss_reset(G3Loss *w)
{
    uint16_t seed = w->seed;
    g3_loss_init(w, seed);
}

int g3_loss_missing(G3Loss *w, uint16_t *resend, int max_resend)
{
    if (!w->armed || w->start == w->end)
        return 0;
    int n = 0;
    uint16_t cursor = (uint16_t)((w->start + G3_SEQ_STEP) & G3_SEQ_MASK);
    uint16_t stop = (uint16_t)((w->end + G3_SEQ_STEP) & G3_SEQ_MASK);
    int steps = 0;
    while (cursor != stop && n < max_resend && steps < 512) {
        if (!have_get(w, cursor))
            resend[n++] = cursor;
        cursor = (uint16_t)((cursor + G3_SEQ_STEP) & G3_SEQ_MASK);
        steps++;
    }
    if (n)
        w->requests++;
    return n;
}

int g3_loss_push(G3Loss *w, uint16_t seq, uint16_t *resend, int max_resend)
{
    seq &= G3_SEQ_MASK;
    if (!w->armed) {
        w->start = w->end = seq;
        w->armed = 1;
        return 0;
    }
    have_set(w, seq);
    {
        uint16_t ahead = g3_seq_ahead(seq, w->end);
        if (ahead > 0 && ahead < 0x8000)
            w->end = seq;
    }
    {
        uint16_t nxt = (uint16_t)((w->start + G3_SEQ_STEP) & G3_SEQ_MASK);
        while (have_get(w, nxt)) {
            have_clr(w, nxt);
            w->start = nxt;
            nxt = (uint16_t)((w->start + G3_SEQ_STEP) & G3_SEQ_MASK);
        }
    }
    for (int i = 0; i < 65536; i += G3_SEQ_STEP) {
        uint16_t s = (uint16_t)i;
        if (have_get(w, s) && g3_seq_ahead(w->end, s) > 2048)
            have_clr(w, s);
    }
    return g3_loss_missing(w, resend, max_resend);
}

void g3_frame_init(G3Frame *f)
{
    memset(f, 0, sizeof *f);
    f->frame = -1;
}

void g3_frame_clear(G3Frame *f)
{
    for (int i = 0; i < G3_MAX_PARTS; i++) {
        free(f->part[i]);
        f->part[i] = NULL;
        f->plen[i] = 0;
    }
    f->frame = -1;
    f->n_parts = 0;
}

uint8_t *g3_frame_push(G3Frame *f, const G3Video *v, size_t *out_len)
{
    *out_len = 0;
    if (v->n_parts <= 0 || v->n_parts > G3_MAX_PARTS || v->part >= v->n_parts)
        return NULL;
    if (f->frame != (int)v->frame) {
        for (int i = 0; i < G3_MAX_PARTS; i++) {
            free(f->part[i]);
            f->part[i] = NULL;
            f->plen[i] = 0;
        }
        f->frame = v->frame;
        f->n_parts = v->n_parts;
    }
    free(f->part[v->part]);
    f->part[v->part] = malloc(v->h264_len ? v->h264_len : 1);
    if (!f->part[v->part])
        return NULL;
    memcpy(f->part[v->part], v->h264, v->h264_len);
    f->plen[v->part] = v->h264_len;

    size_t total = 0;
    for (int i = 0; i < f->n_parts; i++) {
        if (!f->part[i])
            return NULL;
        total += f->plen[i];
    }
    uint8_t *au = malloc(total ? total : 1);
    if (!au)
        return NULL;
    size_t off = 0;
    for (int i = 0; i < f->n_parts; i++) {
        memcpy(au + off, f->part[i], f->plen[i]);
        off += f->plen[i];
        free(f->part[i]);
        f->part[i] = NULL;
        f->plen[i] = 0;
    }
    f->complete++;
    *out_len = total;
    return au;
}
