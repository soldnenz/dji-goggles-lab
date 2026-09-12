SDK := $(shell xcrun --sdk macosx --show-sdk-path)
CC := clang
CXX := clang++
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2
USER_LIBS := -framework IOKit -framework CoreFoundation

KEXT_NAME := aspan_usb_bridge
KEXT_BUNDLE := $(KEXT_NAME).kext
KEXT_BIN := $(KEXT_BUNDLE)/Contents/MacOS/$(KEXT_NAME)
KEXT_FLAGS := -std=gnu++17 -arch arm64e -mkernel -nostdlib -fno-builtin \
	-fno-exceptions -fno-rtti -fapple-kext -fno-stack-protector \
	-DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE \
	-isysroot $(SDK) \
	-I$(SDK)/System/Library/Frameworks/Kernel.framework/Headers
KEXT_LDFLAGS := -arch arm64e -mkernel -nostdlib -fapple-kext \
	-isysroot $(SDK) \
	-L$(SDK)/usr/lib -lkmodc++ -lkmod -lcc_kext \
	-Wl,-kext -Wl,-undefined,dynamic_lookup

.PHONY: all userspace kext clean

all: userspace

userspace: probe watch publish link

probe: probe.c
	$(CC) $(CFLAGS) $< $(USER_LIBS) -o $@

watch: watch.c
	$(CC) $(CFLAGS) $< $(USER_LIBS) -o $@

publish: userspace/publish.c userspace/gadget.c userspace/gadget.h
	$(CC) $(CFLAGS) userspace/publish.c userspace/gadget.c $(USER_LIBS) -o $@

link: userspace/link.c userspace/gadget.c userspace/gadget.h
	$(CC) $(CFLAGS) userspace/link.c userspace/gadget.c $(USER_LIBS) -o $@

kext: $(KEXT_BIN)

KEXT_CFLAGS := -std=c11 -arch arm64e -mkernel -nostdlib -fno-builtin \
	-fno-stack-protector \
	-DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE \
	-isysroot $(SDK) \
	-I$(SDK)/System/Library/Frameworks/Kernel.framework/Headers

$(KEXT_BIN): kext/aspan_usb_bridge.cpp kext/aspan_usb_bridge.h kext/kmod_info.c kext/Info.plist
	mkdir -p $(KEXT_BUNDLE)/Contents/MacOS
	cp kext/Info.plist $(KEXT_BUNDLE)/Contents/Info.plist
	$(CXX) $(KEXT_FLAGS) kext/aspan_usb_bridge.cpp -c -o /tmp/$(KEXT_NAME).o
	$(CC) $(KEXT_CFLAGS) kext/kmod_info.c -c -o /tmp/$(KEXT_NAME)_kmod.o
	$(CXX) $(KEXT_LDFLAGS) /tmp/$(KEXT_NAME).o /tmp/$(KEXT_NAME)_kmod.o -o $@
	codesign --force --sign - --deep $(KEXT_BUNDLE)
	@echo "built $(KEXT_BUNDLE)"

clean:
	rm -f probe watch publish link
	rm -rf $(KEXT_BUNDLE)
