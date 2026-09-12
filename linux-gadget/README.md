# linux-gadget — метод 1 на Pi

Тот же USB-роль что `mac-usb/`: очки host, Pi accessory.

```sh
sudo apt install python3
# /boot/firmware/config.txt : dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=. python3 -m pi_endpoint.endpoint --out /tmp/goggles.h264 -v
```
