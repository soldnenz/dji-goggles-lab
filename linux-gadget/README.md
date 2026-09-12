# linux-gadget — method 1 on a Pi

Same USB role as `mac-usb/`: goggles host, Pi is the accessory.

```sh
sudo apt install python3
# /boot/firmware/config.txt : dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=. python3 -m pi_endpoint.endpoint --out /tmp/goggles.h264 -v
PYTHONPATH=. python3 -m unittest discover -s tests
```
