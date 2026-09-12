.PHONY: userspace kext g3lv clean

userspace:
	$(MAKE) -C mac-usb userspace

kext:
	$(MAKE) -C mac-usb kext

g3lv:
	$(MAKE) -C ip-liveview/c

clean:
	$(MAKE) -C mac-usb clean
	$(MAKE) -C ip-liveview/c clean
