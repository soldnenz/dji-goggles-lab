# mac-usb — метод 1 на Apple Silicon

Тот же USB-роль что `linux-gadget/`.
[docs/01-usb-gadget.md](../docs/01-usb-gadget.md),
[docs/03-macos-kext.md](../docs/03-macos-kext.md).

```sh
make userspace
make kext
./scripts/stage.sh
sudo ./link --controller usb-drd0
./scripts/unstage.sh
```
