# Mac USB gadget — Method 1 implementation

Same method as `linux-gadget/` (goggles USB host, computer is accessory).
Darwin plumbing: kext on `IOUSBDeviceController`. See
[docs/01-usb-gadget.md](../docs/01-usb-gadget.md) and
[docs/03-macos-kext.md](../docs/03-macos-kext.md).

```sh
make userspace
make kext
./scripts/stage.sh
sudo ./link --controller usb-drd0
./scripts/unstage.sh
```
