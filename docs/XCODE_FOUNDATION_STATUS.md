# Xcode foundation status

**Status:** scaffolded from Linux; must be generated and compiled on Jose's Mac with Xcode.

## Added

```text
apple/HermesCapture/
├── project.yml
├── Apps/
│   ├── iOS/
│   ├── Watch/
│   └── Shared/
└── Packages/HermesCore/
```

## HermesCore currently includes

- `CapturePayloadV1` contract matching `mobile_capture.v1`.
- Canonical route/domain enums:
  - `megan.expense_capture`
  - `aura.reminder_capture`
  - `aura.grocery_capture`
  - `aura.home_action`
  - `aura.general_life_capture`
  - `argos.general_capture`
- HMAC V2 signer:
  - `X-Webhook-Timestamp`
  - `X-Webhook-Signature-V2 = HMAC_SHA256(secret, "<timestamp>.<raw_body>")`
- `WebhookClient` that signs and sends exact encoded JSON bytes.
- `FileOutboxStore` actor for local idempotent queue primitives.
- `QuickActionKind` + `CaptureFactory` for Watch-first actions.
- `CaptureResponseV1` decoding for BFF response JSON.

## XcodeGen

Generate project on macOS:

```bash
cd apple/HermesCapture
brew install xcodegen # if needed
xcodegen generate
open HermesCapture.xcodeproj
```

## SwiftPM tests on macOS

```bash
cd apple/HermesCapture/Packages/HermesCore
swift test
```

Expected test coverage:

- payload JSON contract keys;
- HMAC V2 known vector;
- required webhook headers;
- dry-run quick-action payload factory.

## Linux verification performed

This environment does not have Swift/Xcode installed, so the Apple scaffold could not be compiled here. Verification performed instead:

- Python backend tests still pass.
- Python `py_compile` passes for backend files.
- Static repository checks confirm Apple scaffold files exist and no obvious sensitive local files are staged.

## Next implementation task

On Mac/Xcode:

1. Generate Xcode project.
2. Run `swift test` for `HermesCore`.
3. Build iOS target.
4. Build watchOS target.
5. Implement real dictation flow in `WatchContentView`:
   - present system text input;
   - create `CapturePayloadV1`;
   - enqueue before network;
   - sign and POST to BFF;
   - show `display_message`.
