# Method 1, Linux implementation

Raspberry Pi `raw_gadget` USB device. Same method as `mac-usb/`.

```sh
sudo apt install python3
# /boot/firmware/config.txt : dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=. python3 -m pi_endpoint.endpoint --out /tmp/goggles.h264 -v
PYTHONPATH=. python3 -m unittest discover -s tests
```

No license agent, no HWID, no signing keys. Phone-app capture sequences
with unique identifiers were not imported.
