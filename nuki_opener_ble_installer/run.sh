#!/usr/bin/with-contenv bashio
set -e

TARGET=/homeassistant/custom_components/nuki_opener_ble

bashio::log.info "Installing Nuki Opener (Bluetooth) integration to ${TARGET}"
mkdir -p /homeassistant/custom_components
rm -rf "${TARGET}"
cp -r /integration "${TARGET}"

VERSION=$(jq -r .version "${TARGET}/manifest.json")
bashio::log.info "Installed version ${VERSION}."
bashio::log.info "Restart Home Assistant, then add the 'Nuki Opener (Bluetooth)' integration."
