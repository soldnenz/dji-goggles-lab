# Method 1 kext on macOS

This is Apple policy, not USB.

| Check | What happens |
| --- | --- |
| Recovery, reduced security / allow third-party kexts | without this `kmutil load` fails on a good binary |
| Privacy & Security → Allow `com.aspan.usbbridge` | first copy into `/Library/Extensions` |
| AuxKC | often needs a reboot after Allow; if `kmutil showloaded` has no `aspan`, you are still here |
| Signature | `make kext` is ad-hoc (`codesign --sign -`). Fine for a lab Mac. Not notarized. |

```sh
cd mac-usb
make kext
./scripts/stage.sh
kmutil showloaded | grep aspan
./scripts/unstage.sh
```

| kmutil noise | Actual problem |
| --- | --- |
| not approved | Allow, run `stage.sh` again |
| AuxKC / collection | reboot once |
| wrong arch | Makefile is `arm64e` only |
| SIP | Recovery. Do not cargo-cult Intel `csrutil` |

The kext leases the gadget description so a dead userspace process does
not leave the controller stuck as an accessory. After `unstage.sh`, reboot
if AuxKC still has the bundle.

Do not commit the built `.kext`, `probe` IORegistry dumps, or Apple
signing identities.
