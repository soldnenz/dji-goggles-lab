# g3lv

C-клиент DJI Goggles 3 IP liveview. POSIX (macOS / Linux).

Пишет Annex-B в `--out`. Декодера нет: High Profile без IDR, VideoToolbox
и `ffplay -f h264` на этом стриме тупят.

```
make
./g3lv --wifi -v
./g3lv --wired --boost --no-rtx
```

`pkg-config libusb-1.0` — bitrate DUML на USB MI04 (if 4, без
set_configuration). Нет libusb — собирается всё равно, hint идёт UDP type-5.

Бинарник `g3lv` в git не тащи.
