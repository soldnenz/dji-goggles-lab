# linux-gadget

Очки — USB host, Pi — accessory. То же, что `mac-usb/`.

```sh
sudo apt install python3
# /boot/firmware/config.txt : dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=. python3 -m pi_endpoint.endpoint --out /tmp/goggles.h264 -v
```
