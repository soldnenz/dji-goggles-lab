# ip-liveview — метод 2, только Goggles 3

Приёмник: **C**, `c/g3lv`. Один UDP на Wi-Fi / RNDIS / tetherkit.

```sh
make -C c
./c/g3lv --wifi --out live.h264 -v
./c/g3lv --wired --boost -v
```

Python (`protocol.py` / `receiver.py` / `liveview.py`) — тот же протокол,
плюс декодер в окно. `mac_wired.py` поднимает NIC на маке.

Графики и разбор: [../README.md](../README.md), [docs/02-ip-liveview.md](../docs/02-ip-liveview.md).
