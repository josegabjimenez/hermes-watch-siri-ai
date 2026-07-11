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

## SwiftPM tests on macOS

Use the Xcode-selected Apple toolchain so XCTest is available:

```bash
cd apple/HermesCapture/Packages/HermesCore
xcrun --find swift
xcrun swift --version
xcrun swift test
```

If plain `swift test` reports `no such module 'XCTest'` or `no such module 'Testing'`, inspect `which -a swift`, `echo "$TOOLCHAINS"`, and `xcode-select -p`; a standalone Swift toolchain is being selected instead of Xcode. Do not add `swift-corelibs-xctest` to this Apple package as a workaround because its macOS build expects private Foundation build flags.

## Linux limitation

This repository was scaffolded from Linux, so Xcode project generation/build must be verified on Jose's Mac with Xcode. The Swift package is written to be testable with SwiftPM when Swift is available.
