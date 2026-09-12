# ip-liveview — method 2, Goggles 3 only

Wi-Fi, Windows RNDIS, and macOS tetherkit all use `protocol.py`.
[docs/02-ip-liveview.md](../docs/02-ip-liveview.md).

```sh
python3 -m pip install -r requirements.txt
python3 receiver.py --wifi --out live.h264 -v
python3 liveview.py --wifi
python3 mac_wired.py --view
python3 -m unittest discover -s tests
```
