#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum {
    G3_HDR = 8,
    G3_FLAG = 0x8000,
    G3_VIDEO_OFF = 0x14,
    G3_SEQ_STEP = 8,
    G3_SEQ_MASK = 0xFFFF,
    G3_TYPE_HANDSHAKE = 0,
    G3_TYPE_DATA = 1,
    G3_TYPE_VIDEO = 2,
    G3_TYPE_ACK = 4,
    G3_TYPE_CMD = 5,
    G3_MAX_RESEND = 16,
    G3_MAX_PARTS = 64,
    G3_BOOST_KBPS = 22500,
    G3_BOOST_SENDER = 0x1B,
    G3_BOOST_RECEIVER = 0xEE,
    G3_BOOST_CMDSET = 0x51,
    G3_BOOST_CMD = 0x29
};

typedef struct {
    uint16_t length;
    uint16_t session;
    uint16_t seq;
    uint8_t type;
} G3Header;

typedef struct {
    G3Header hdr;
    uint16_t win_start;
    uint16_t win_end;
    uint8_t frame;
    uint8_t n_parts;
    uint8_t part;
    const uint8_t *h264;
    size_t h264_len;
} G3Video;

typedef struct {
    uint16_t seed;
    uint16_t start;
    uint16_t end;
    int armed;
    unsigned requests;
    uint8_t have[8192];
} G3Loss;

typedef struct {
    int frame;
    int n_parts;
    int complete;
    uint8_t *part[G3_MAX_PARTS];
    size_t plen[G3_MAX_PARTS];
} G3Frame;

uint8_t g3_xor7(const uint8_t *p);
void g3_put16(uint8_t *p, uint16_t v);
uint16_t g3_get16(const uint8_t *p);
uint16_t g3_seq_ahead(uint16_t newer, uint16_t older);

int g3_parse_header(const uint8_t *p, size_t n, G3Header *out);
size_t g3_pack_header(uint8_t *out, uint16_t length, uint16_t session, uint16_t seq, uint8_t type);
size_t g3_build_handshake(uint8_t *out /*48*/, uint16_t session);
uint16_t g3_handshake_seed(const uint8_t *pkt);

size_t g3_build_duml(uint8_t *out, size_t cap, uint8_t sender, uint8_t receiver, uint16_t seq,
                     uint8_t cmdset, uint8_t cmd, const uint8_t *payload, size_t plen);
size_t g3_build_bitrate_boost(uint8_t *out, size_t cap, uint16_t seq, uint32_t kbps);
size_t g3_build_type5(uint8_t *out, size_t cap, uint16_t session, uint16_t seq,
                      uint16_t win_s, uint16_t win_e, const uint8_t *duml, size_t dlen, uint8_t counter);
size_t g3_build_ack(uint8_t *out, size_t cap, uint16_t session, uint16_t win_s, uint16_t win_e,
                    const uint16_t *resend, int nresend, uint16_t t3s, uint16_t t3e,
                    uint16_t t5s, uint16_t t5e, const uint8_t *duml, size_t dlen);

int g3_parse_video(const uint8_t *p, size_t n, G3Video *out);
int g3_is_data(const uint8_t *p, size_t n);

void g3_loss_init(G3Loss *w, uint16_t seed);
void g3_loss_reset(G3Loss *w);
int g3_loss_push(G3Loss *w, uint16_t seq, uint16_t *resend, int max_resend);
int g3_loss_missing(G3Loss *w, uint16_t *resend, int max_resend);

void g3_frame_init(G3Frame *f);
void g3_frame_clear(G3Frame *f);
/* returns malloc'd Annex-B AU or NULL; caller frees */
uint8_t *g3_frame_push(G3Frame *f, const G3Video *v, size_t *out_len);

int g3_mi04_open(char *err, size_t errlen);
int g3_mi04_write(const uint8_t *p, size_t n);
void g3_mi04_close(void);
int g3_mi04_claimed(void);
const char *g3_mi04_detail(void);
