# App Intents and Siri dry-run capture

**Status:** implemented for iOS 17+ and watchOS 10+; Xcode simulator/device validation required.

## Intents

Hermes exposes four authenticated App Intents:

```text
Registrar gasto en Hermes       → megan.expense_capture
Crear recordatorio en Hermes    → aura.reminder_capture
Agregar al mercado en Hermes    → aura.grocery_capture
Capturar con Hermes             → argos.general_capture
```

Each intent asks the system for free-form text, creates the same `CapturePayloadV1` used by the Watch UI, persists it before network access, signs it with HMAC V2, and returns the synchronous BFF `display_message` to Siri/Shortcuts.

## Suggested Spanish phrases

```text
Registrar gasto con Hermes
Nuevo gasto en Hermes
Crear recordatorio con Hermes
Recuérdame algo con Hermes
Agregar al mercado con Hermes
Mercado en Hermes
Capturar con Hermes
Nueva captura en Hermes
```

The phrases contain no endpoint, credentials, capture content, or personal data.

## Authentication policy

Every intent declares:

```swift
.requiresLocalDeviceAuthentication
```

The system must authenticate/unlock the local device according to platform policy before execution. `openAppWhenRun` remains `false` so Siri can return the result directly.

## Local-first delivery

```text
Siri/App Shortcut
  → free-form text parameter
  → CapturePayloadV1 with modality app_intent
  → file outbox
  → route-scoped secret from local Keychain
  → direct HTTPS + HMAC V2
  → synchronous dry-run response
  → spoken/displayed result
```

The payload remains:

```text
dry_run: true
allow_write: false
```

## Execution surfaces

- On iPhone, the intent uses the endpoint and Keychain configured in the iPhone app and the iPhone-local outbox.
- On Watch, it uses the endpoint and Keychain provisioned through the secure bootstrap and the Watch-local outbox.
- WatchConnectivity is not required for the capture request after Watch provisioning.

The iPhone companion now shows aggregate counts for its own Siri/App Intent outbox and can retry deliverable iPhone items.

## Concurrent outbox hardening

The outbox now uses a sibling `outbox.json.lock` advisory file lock around every read-modify-write operation. This prevents separate UI/App Intent store instances from silently overwriting each other's captures inside the same app container.

The lock contains no payload or credentials and is released automatically when its file descriptor closes or the process exits.

## Controlled offline test

Debug builds support the environment variable:

```text
HERMES_SIMULATE_OFFLINE=1
```

When enabled, delivery fails after `markSending` and transitions the already-persisted item to `failed` with sanitized network state. It never contacts the BFF.

Manual flow:

1. Add the environment variable to the Watch scheme and run.
2. Capture text from the Watch UI.
3. Confirm the item appears `Falló` in history.
4. Remove the variable and relaunch.
5. Tap **Reintentar pendientes**.
6. Confirm the same item becomes `Enviado` with attempt count `2`.

This hook is compiled only in Debug builds.

## Automated verification

HermesCore coverage includes:

- App Intent modality while preserving dry-run/no-write context;
- 20 concurrent enqueues through separate store instances with zero lost items;
- network failure preserving the original request ID;
- successful retry to `sent` with attempt count `2`;
- existing HMAC, endpoint, headers, idempotency, and response safety tests.

## Remaining Apple QA

- compile both generated Xcode targets and inspect App Intents metadata extraction;
- verify shortcuts appear in the Shortcuts app;
- invoke each Spanish phrase on iPhone Simulator;
- invoke on Watch Simulator where Siri support permits;
- run on a physical Apple Watch without relying on iPhone reachability;
- verify authentication and locked-device behavior;
- verify privacy manifest/App Privacy declarations before distribution.
