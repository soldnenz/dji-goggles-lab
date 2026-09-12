.PHONY: userspace kext clean

userspace:
	$(MAKE) -C mac-usb userspace

kext:
	$(MAKE) -C mac-usb kext

clean:
	$(MAKE) -C mac-usb clean
