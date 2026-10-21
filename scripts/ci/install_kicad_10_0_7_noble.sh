#!/usr/bin/env bash
# Primary stable KiCad 10.0.7 CLI on GitHub's Ubuntu 24.04 runner.
# PPA outages / version drift are infra failures, not canary successes.
set -euo pipefail
if [[ "$(. /etc/os-release && printf '%s' "$VERSION_ID")" != '24.04' ]]; then
  echo 'The KiCad 10.0.7 primary canary requires Ubuntu 24.04.' >&2
  exit 1
fi
sudo add-apt-repository -y ppa:kicad/kicad-10.0-releases
sudo apt-get -o Acquire::Retries=4 -o APT::Update::Error-Mode=any update
for package in kicad kicad-symbols kicad-footprints; do
  candidate="$(apt-cache policy "$package" | awk '/Candidate:/ { print $2; exit }')"
  if [[ "$candidate" != 10.0.7* ]]; then
    echo "Expected KiCad 10.0.7 package $package; refusing ${candidate:-none}." >&2
    apt-cache policy "$package" >&2
    exit 1
  fi
done
sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=4 install \
  --yes --no-install-recommends kicad kicad-symbols kicad-footprints
version="$(kicad-cli version)"
if [[ "$version" != '10.0.7' ]]; then
  echo "Installed CLI must be 10.0.7, found: $version" >&2
  exit 1
fi
for required in /usr/share/kicad/symbols/Device.kicad_sym \
                /usr/share/kicad/footprints/Resistor_SMD.pretty; do
  if [[ ! -e "$required" ]]; then
    echo "KiCad 10.0.7 required library missing: $required" >&2
    exit 1
  fi
done
printf 'KiCad 10.0.7 primary canary installer accepted: %s\n' "$(command -v kicad-cli)"
