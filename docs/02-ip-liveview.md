# IP liveview, Goggles 3

G3 отдаёт картинку на UDP 9003, если включён Share Live View. Это не AOA.

На очках: Share Live View to a Mobile Device via Wi-Fi, или USB с
выключенным OTG.

| | L2 | у себя | очки |
| --- | --- | --- | --- |
| Wi-Fi | AP очков | DHCP | `192.168.2.1:9003` |
| USB Windows | Remote NDIS | `192.168.60.1/24`, без gateway | `192.168.60.2:9003` |
| USB macOS | `tetherkit-cli` → `feth0` | тот же /24 | тот же peer |

Клиент: `ip-liveview/c/g3lv`. Python (`protocol.py`, `liveview.py`) —
тот же протокол, плюс декодер в окно. `mac_wired.py` только поднимает
адрес на маке: inbox RNDIS у Apple нет.

## Заголовок UDP, 8 байт LE

| off | | |
| --- | --- | --- |
| 0 | u16 | length \| `0x8000` |
| 2 | u16 | session |
| 4 | u16 | seq |
| 6 | u8 | type |
| 7 | u8 | XOR байт 0..6 |

Несовпадение XOR или `(len & 0x7FFF) !=` размер датаграммы — дроп.

| type | |
| --- | --- |
| 0 | handshake, 48 байт, хвост константа |
| 1 | окна + DUML, ~10 Hz |
| 2 | видео, H.264 с `+0x14`, seq шаг 8 |
| 3 | file, на проводе видел, здесь не использую |
| 4 | ACK от клиента; без него стрим падает |
| 5 | command |
| 6 | ещё ACK |

В type-4 список resend — пропущенные type-2 seq с шагом 8. Если список
не начинается с первой дыры, G3 выкидывают его целиком. Так ведёт себя
прошивка; в чужом `rtx.rs` это тоже заложено.

MI04: `2CA3:0020` interface 4, class `ff/43/01`. DUML bitrate `0x51/0x29`,
sender `0x1B`, 22500 kbps каждые 250 ms. Claim if 4, без reset и без
`set_configuration`.

## Декодер

High Profile, IDR почти нет. VideoToolbox ждёт RAP. `ffplay -f h264` с
пайпа буферит и после одной потерянной AU мажет всё дальше.
`liveview.py` открывает h264 с `FLAG2_SHOW_ALL` + `LOW_DELAY` и кормит
ffplay raw YUV. Чёрный экран на маке чаще декодер, чем «не тот протокол».
