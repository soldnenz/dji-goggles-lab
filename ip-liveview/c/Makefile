CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic
LDFLAGS ?=
LDLIBS ?=

LIBUSB_CFLAGS := $(shell pkg-config --cflags libusb-1.0 2>/dev/null)
LIBUSB_LIBS := $(shell pkg-config --libs libusb-1.0 2>/dev/null)
ifneq ($(strip $(LIBUSB_LIBS)),)
  CFLAGS += -DUSE_LIBUSB $(LIBUSB_CFLAGS)
  LDLIBS += $(LIBUSB_LIBS)
endif

.PHONY: all clean

all: g3lv

g3lv: g3lv.o protocol.o mi04.o
	$(CC) $(LDFLAGS) -o $@ $^ $(LDLIBS)

g3lv.o: g3lv.c g3lv.h
protocol.o: protocol.c g3lv.h
mi04.o: mi04.c g3lv.h

clean:
	rm -f g3lv *.o
