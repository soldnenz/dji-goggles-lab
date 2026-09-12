#!/bin/sh
# Copy the kext to /Library/Extensions and load it. Needs 1TR third-party kexts.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEXT="$ROOT/aspan_usb_bridge.kext"
test -d "$KEXT/Contents/MacOS" || { echo "build first: make kext"; exit 1; }
STAGE="/Library/Extensions/aspan_usb_bridge.kext"
echo "installing $STAGE (root:wheel)"
sudo rm -rf "$STAGE"
sudo cp -R "$KEXT" "$STAGE"
sudo chown -R root:wheel "$STAGE"
sudo chmod -R go-w "$STAGE"
sudo kmutil load -p "$STAGE"
echo "If Privacy & Security asks Allow — approve com.aspan.usbbridge and rerun."
echo "AuxKC may need a reboot. Unload: $ROOT/scripts/unstage.sh"
