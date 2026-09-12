.PHONY: userspace kext clean test

userspace:
	$(MAKE) -C mac-usb userspace

kext:
	$(MAKE) -C mac-usb kext

clean:
	$(MAKE) -C mac-usb clean

test:
	python3 -m unittest discover -s ip-liveview/tests
	PYTHONPATH=linux-gadget python3 -m unittest discover -s linux-gadget/tests
