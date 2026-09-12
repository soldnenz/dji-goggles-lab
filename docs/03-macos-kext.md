# Loading the Method 1 kext on macOS

This is the operational part people get stuck on. It is not USB protocol.
Third-party kexts on Apple Silicon are a Recovery-time policy decision.

## What Apple actually checks

1. **SIP / reduced security.** In Recovery: hold power → Options →
   Startup Security. Allow third-party kernel extensions (the exact label
   varies by macOS version). Without this, `kmutil load` fails even with a
   perfect binary.
2. **User approval.** System Settings → Privacy & Security → Allow the
   developer id `com.aspan.usbbridge` after the first copy into
   `/Library/Extensions`.
3. **Auxiliary Kernel Collection (AuxKC).** Many builds will not bind the
   personality until the kext is in AuxKC. That often means **reboot** after
   Allow. If `kmutil showloaded` never lists `com.aspan.usbbridge`, you are
   still in this step — not in USB debugging yet.
4. **Signature.** `make kext` ad-hoc signs (`codesign --sign -`). That is
   enough for a personal lab Mac with reduced security. It is not notarized
   and must not be shipped as a signed product from this repo.

## Commands used in this lab

```sh
cd mac-usb
make kext
./scripts/stage.sh     # root:wheel copy + kmutil load
kmutil showloaded | grep aspan
./scripts/unstage.sh   # unload + delete from /Library/Extensions
```

If load fails, read the kmutil error before changing USB code:

- not approved → Allow in Privacy & Security, retry `stage.sh`;
- AuxKC / collection → reboot once;
- wrong arch → this Makefile is `arm64e` (Apple Silicon only);
- SIP blocked → Recovery, not `csrutil` folklore from Intel years.

## Safety

- Use a spare volume or a Mac you can reinstall. A wedged USB device
  controller is why the kext **leases** the gadget description.
- `unstage.sh` restores nothing if macOS already rebuilt AuxKC around the
  kext; reboot after unload.
- Do not disable SIP globally “to make USB work”. Reduced kext policy is
  the documented lab switch.

## What not to commit

- The built `aspan_usb_bridge.kext` bundle (ad-hoc signature, machine
  specific).
- IORegistry snapshots from `probe` (paths and serial-ish properties).
- Apple Developer identities, provisioning profiles, or notary API keys.
