# ip-liveview — метод 2, только Goggles 3

Wi-Fi, Windows RNDIS и tetherkit на маке — один `protocol.py`.
[docs/02-ip-liveview.md](../docs/02-ip-liveview.md).

```sh
python3 -m pip install -r requirements.txt
python3 receiver.py --wifi --out live.h264 -v
python3 liveview.py --wifi
python3 mac_wired.py --view
```
