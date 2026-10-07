#!/bin/bash
# Creates a self-signed code-signing certificate "Lectern Dev" in your login keychain, once.
# build-app.sh signs with it when it exists, so macOS keeps the Accessibility grant across
# rebuilds (an ad-hoc signature changes with every build). Free; not a substitute for
# notarization, so other Macs still need right-click → Open the first time.
set -euo pipefail
if security find-identity -v -p codesigning | grep -q "Lectern Dev"; then
  echo "certificate 'Lectern Dev' already exists"; exit 0
fi
tmp=$(mktemp -d)
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$tmp/key.pem" -out "$tmp/cert.pem" \
  -subj "/CN=Lectern Dev" -addext "keyUsage=digitalSignature" -addext "extendedKeyUsage=codeSigning" \
  -addext "basicConstraints=CA:FALSE" 2>/dev/null
# macOS's importer only reads the older PKCS12 encryption; OpenSSL 3 needs -legacy for that.
legacy=""; openssl version | grep -q "^OpenSSL 3" && legacy="-legacy"
openssl pkcs12 -export $legacy -out "$tmp/lectern-dev.p12" -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -passout pass:lectern
security import "$tmp/lectern-dev.p12" -k ~/Library/Keychains/login.keychain-db -P lectern -T /usr/bin/codesign >/dev/null
# Trust it for code signing (macOS may ask for your login password once).
security add-trusted-cert -p codeSign -k ~/Library/Keychains/login.keychain-db "$tmp/cert.pem"
rm -rf "$tmp"
security find-identity -v -p codesigning | grep "Lectern Dev"
