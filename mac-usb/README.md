# mac-usb — method 1 on Apple Silicon

Same USB role as `linux-gadget/`. Notes: [docs/01-usb-gadget.md](../docs/01-usb-gadget.md),
[docs/03-macos-kext.md](../docs/03-macos-kext.md).

```sh
make userspace
make kext
./scripts/stage.sh
sudo ./link --controller usb-drd0
./scripts/unstage.sh
```
