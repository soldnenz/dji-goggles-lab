# kext на macOS

Без reduced security kext просто не загрузится, какой бы ни был бинарь.

| | |
| --- | --- |
| Recovery → reduced security / third-party kexts | иначе `kmutil load` отшивает |
| Privacy & Security → Allow `com.aspan.usbbridge` | после копирования в `/Library/Extensions` |
| AuxKC | часто нужен ребут после Allow; нет `aspan` в `kmutil showloaded` — ещё не сел |
| подпись | `make kext` ad-hoc (`codesign --sign -`). Нотаризации нет |

```sh
cd mac-usb
make kext
./scripts/stage.sh
kmutil showloaded | grep aspan
./scripts/unstage.sh
```

| kmutil | |
| --- | --- |
| not approved | Allow, потом снова `stage.sh` |
| AuxKC / collection | ребут |
| wrong arch | в Makefile только `arm64e` |
| SIP | Recovery; готовые `csrutil` с хабра для Intel не копировать |

Kext держит lease на gadget description: userspace умер — откат на NCM.
После `unstage.sh` бандл иногда ещё в AuxKC, тогда ребут.

Собранный `.kext`, дампы `probe` и сертификаты Apple в этот репозиторий
не кладутся.
