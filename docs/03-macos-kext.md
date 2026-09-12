# Method 1 kext на macOS

Это не USB. Это политика Apple, и она бесит.

| проверка | что будет |
| --- | --- |
| Recovery → reduced security / third-party kexts | без этого `kmutil load` шлёт даже идеальный бинарь |
| Privacy & Security → Allow `com.aspan.usbbridge` | после первого копирования в `/Library/Extensions` |
| AuxKC | часто ребут после Allow; `kmutil showloaded` без `aspan` = ты ещё тут |
| подпись | `make kext` ad-hoc (`codesign --sign -`). Для лабы ок. Нотаризации нет и не будет |

```sh
cd mac-usb
make kext
./scripts/stage.sh
kmutil showloaded | grep aspan
./scripts/unstage.sh
```

| kmutil пишет | на самом деле |
| --- | --- |
| not approved | Allow, снова `stage.sh` |
| AuxKC / collection | один ребут |
| wrong arch | Makefile только `arm64e` |
| SIP | Recovery. Intel-`csrutil` с хабра не копипастить |

Kext держит lease на gadget description: userspace помер — откат на NCM,
а не вечный accessory на контроллере. После `unstage.sh` если AuxKC
ещё держит бандл — ребут.

Собранный `.kext`, дампы `probe` и Apple-сертификаты в паблик не нести.
