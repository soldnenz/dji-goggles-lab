# ip-liveview (Goggles 3, UDP :9003)

```sh
make -C c
./c/g3lv --wifi --out live.h264 -v
./c/g3lv --wired --boost -v
```

Wi-Fi, Windows RNDIS и tetherkit на маке — один протокол.
Python (`receiver.py`, `liveview.py`) если нужен декодер в окно.
`mac_wired.py` поднимает `192.168.60.1` на `feth0`.

[README](../README.md), [docs/02-ip-liveview.md](../docs/02-ip-liveview.md).
