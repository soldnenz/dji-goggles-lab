# g3lv

UDP-клиент liveview Goggles 3. macOS / Linux. Пишет Annex-B в `--out`.

```
make
./g3lv --wifi -v
./g3lv --wired --boost --no-rtx
```

С `pkg-config libusb-1.0` bitrate DUML идёт на MI04 (interface 4).
Без libusb собирается тоже, hint тогда UDP type-5.
Не вызывать `set_configuration`.
