# HermesCapture Apple App Scaffold

This folder contains the first native Apple app scaffold for the Watch-first Hermes capture system.

## Shape

```text
HermesCapture/
├── project.yml                         # XcodeGen project definition
├── Packages/HermesCore/                # Shared Swift package
├── Apps/iOS/                           # iPhone companion shell
└── Apps/Watch/                         # Watch-first capture shell
```

## Generate Xcode project on macOS

```bash
cd apple/HermesCapture
brew install xcodegen # if needed
xcodegen generate
open HermesCapture.xcodeproj
```

## Build target direction

- iOS app: configuration, endpoint, Keychain bootstrap, history/debug, WatchConnectivity fallback.
- watchOS app: fast capture buttons, dictation, outbox, direct HTTPS to BFF.
- HermesCore: shared payload contract, HMAC V2 signer, webhook client, outbox primitives.

## Current endpoint contract

Development builds should target a tailnet-only HTTPS BFF endpoint:

```text
https://<TAILSCALE_DNS_NAME>:8650/webhooks/mobile-capture-v1
```

Never commit the real route secret. Store it in Keychain and sync to Watch via a reviewed bootstrap flow.

## Linux limitation

This repository was scaffolded from Linux, so Xcode project generation/build must be verified on Jose's Mac with Xcode. The Swift package is written to be testable with SwiftPM when Swift is available.
