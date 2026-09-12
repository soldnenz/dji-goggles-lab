#!/bin/sh
# Unload the kext and remove it from /Library/Extensions.
set -e
echo "unloading com.aspan.usbbridge"
sudo kmutil unload -b com.aspan.usbbridge || true
sudo kmutil clear-staging || true
if test -d /Library/Extensions/aspan_usb_bridge.kext; then
  echo "removing /Library/Extensions/aspan_usb_bridge.kext"
  sudo rm -rf /Library/Extensions/aspan_usb_bridge.kext
fi
echo "If the kext was in AuxKC, reboot. Then: kmutil showloaded | grep aspan"
