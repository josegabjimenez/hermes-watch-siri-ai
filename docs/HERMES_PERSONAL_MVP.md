# Hermes personal MVP · 25 October 2026

Source task: [existing W-R02](https://app.notion.com/p/3ddfcdfcb7b48142bce3fcdd9916c330). Jose approved implementation for his own iPhone and Apple Watch. This delivery prepares code and a reviewable PR; it does not authorize merge, production deployment, financial transactions, or acceptance of device gates.

## Three actions

| Action | Behavior | Evidence required for real use |
| --- | --- | --- |
| Mercado | Add to the existing official list. A committed helper result is required before claiming success. | Reviewed exact Aura helper, official-list identity, normalized matching/pagination, concurrent duplicates, and lost-ACK recovery without changing existing item state. |
| Recordatorio | Create only the requested new reminder with an unambiguous future Bogotá date/time. Unsupported/ambiguous schedules ask for clarification before writing. | Reviewed exact helper and Task readback, frozen date agreement, plus an actual alarm and device notification as described below. |
| Gasto | One COP withdrawal from an existing active asset account. Preview the frozen amount, account, category and budget; require a separate explicit confirmation. | Existing catalogue/rules, COP agreement, durable operation ledger and external-ID readback. A live financial check needs separate authorization. |

General capture/Capturar and Argos dispatch are excluded. Old protocol values/history remain readable; the old general intent is disabled and is not advertised. There are no favorite actions. Cards, installments, transfers, incomes, new accounts/categories/budgets, and modification of preexisting reminders are excluded.

## Confirmation, cancellation, and recovery

Expense preview and confirmation are distinct payloads. The BFF freezes and signs the plan; confirmation does not reinterpret the dictation. Repeated taps reuse the same confirmation request and operation. The adapter uses `external_id=hermes-watch:{operation_id}` and reconciles an uncertain result before any further decision; it never posts again after an uncertain claim.

Cancelling first persists a per-operation tombstone and suppresses unsent confirmations under the same file lock used by delivery claims. Persistence failure does not produce a local success message. A confirmation already attempted or in flight may have committed: local cancellation cannot promise reversal. The UI states that uncertainty and preserves the audit identity. A correlated terminal rejection invalidates a preview durably; a network failure preserves it for safe retry/cancellation. Relaunch does not grant renewed permission.

The `.sent` outbox state means a validated response was received, which can be a preview, clarification, cancellation or rejection. Only `write_committed=true` establishes business success. `writing`/`uncertain` expenses require reconciliation; stale preview responses never claim that an earlier expense did not occur.

Live Watch traffic requires direct HTTPS. The existing phone relay accepts dry-run requests only. A relay smoke test cannot certify Watch live-write connectivity.

## Reminder alert handoff

The external Aura helper is **not included or verified** in this repository. The BFF passes `text`, `request_id`, `created_at`, `timezone`, and `interpreted_due` to it. Both side-effect-free preflight and committed response must attest the same `interpreted_due.start` and `America/Bogota`. The helper must honor the supplied instant rather than reparsing relative time on retry. It must use durable request identity and create-only Task authority. Existing `--no-notify` is preserved because its exact behavior is unknown without the helper source.

A Notion Task and a Calendar event ID do not prove that an alert will reach Jose. Current responses preserve `interpreted_due`, `notification_verified=false`, and `delivery_status=pending_verification`; the display message states Bogotá time and that alerts need verification. No client schedules a local alert or claims delivery.

The smallest real-use path is to verify the existing Calendar integration, rather than add another notification transport:

1. Obtain and review the exact Aura helper source/version and required private deployment configuration. Exercise it against fake Notion/Calendar services, including pagination, duplicate requests, lost ACK/restart, and zero modifications to existing tasks.
2. Confirm the selected calendar is synced to Jose's iPhone and that Calendar notifications and Watch forwarding are enabled as desired. Keep the selected calendar/private IDs outside this public repository.
3. Require event readback with the intended start/`America/Bogota` and an explicit alarm: `reminders.useDefault=false`, `overrides=[{"method":"popup","minutes":0}]`. Read back the newly created Task separately. Event creation or API push subscriptions alone are insufficient.
4. With a separately authorized device/live reminder check, create one short-future reminder and observe its alert on the paired devices. Record the observed device/lock/connectivity conditions without device identifiers. A simulator result cannot establish this gate.
5. If Calendar creation/alarm proof fails after the Task commits, preserve the Task and report that the alert is not scheduled/verified. Replay must not create another Task. Agree on local notifications only if this existing transport cannot satisfy the handoff.

References: [Google Calendar event reminders](https://developers.google.com/workspace/calendar/api/concepts/reminders), [Apple Watch notification behavior](https://developer.apple.com/documentation/watchos-apps/enabling-and-receiving-notifications).

## Build and physical-device handoff

Use the installed Xcode with command-scoped `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer`; do not change the global developer directory. Generate the project with `xcodegen generate` in `apple/HermesCapture`. The bundle IDs stay `dev.josegabjimenez.HermesCapture` and `dev.josegabjimenez.HermesCapture.watchkitapp`, with the companion relationship intact. This recovered candidate remains **0.3.4 (7)**; provenance/commit identify this new artifact, not the version number alone.

Simulator UI tests use a Debug/simulator-only, explicit launch-argument fixture and an isolated per-case outbox. The fixture intercepts every request and cannot reach real services or write configuration/Keychain. Device and Release builds exclude it. Core/backend tests use synthetic data.

The [device setup follow-up](XCODE_DEVICE_SETUP.md) has configured the existing authorized Team with automatic signing. Jose subsequently authorized normal profile renewal and installation onto his existing pair. The signed iOS/Watch build and renewed profiles are verified; Hermes 0.3.4 (7) is installed and launches on the iPhone after developer trust. Direct Watch installation is blocked by its Bluetooth tunnel, and Jose reports companion installation returns to the Install button. Its actual installer rejection remains unknown; the next diagnostic step needs the paired phone connected over USB. Bundle IDs remain unchanged. After Watch installation/launch are verified, exercise:

- each Siri phrase on iPhone and Watch; expense opens review and requires tapping Register;
- Watch direct HTTPS with the phone absent; locked/unlocked and cold-start/bootstrap behavior;
- offline capture, retry of the same item, double tap, ACK loss, relaunch, cancellation and expiry;
- truthful per-action confirmation and actual reminder notification arrival;
- privacy manifests in the signed archive and local data retention/protection.

Unsigned builds, simulator tests, signed archive creation, physical installation, live-domain behavior, and human acceptance are separate gates. Current results and remaining gates are in [the verification report](verification/2026-10-25/REPORT.md).
