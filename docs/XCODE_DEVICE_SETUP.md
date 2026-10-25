# Physical-device setup · 25 October 2026

Jose requested Xcode setup so that he only needs to test Hermes on his Watch. This continues PR #1 and the existing candidate; it does not authorize merging or deploying the backend.

## Configured locally

The generated project is `apple/HermesCapture/HermesCapture.xcodeproj`. Both product targets now reference `Config/Signing.xcconfig`, which optionally includes the ignored `Signing.xcconfig.local` in that directory. The local file supplies the existing personal development Team and existing signing identity; neither is committed. Automatic signing remains enabled, the bundle IDs and companion relationship are unchanged, and regenerating the Xcode project preserves this setup.

The Team was resolved from the recovered project and independently matched to the current Apple Development certificate. There is no Team choice left for Jose to make. The existing certificate is valid through August 19, 2027. No new identity, certificate or device registration was created.

## Actual device/build state

| Item | Verified state |
| --- | --- |
| Toolchain | Installed Xcode 27.0 (27A5237l), command-scoped `DEVELOPER_DIR`; global selection unchanged. |
| iPhone | Existing paired physical phone, iOS 27.2; Developer Mode enabled; available as an iOS build destination over the local network. |
| Apple Watch | Existing paired physical Watch, watchOS 27.0; Developer Mode enabled; available as a watchOS build destination. |
| Schemes | `HermesCaptureiOS` builds the companion with embedded Watch; `HermesCaptureWatch` targets the physical Watch. Both generated launch actions point to the corresponding app. |
| Local configuration check | Both schemes inherit the resolved Team and automatic signing, with no manual provisioning-profile override. An unsigned iOS device build, including its embedded Watch app, passed after this configuration change. |
| Existing installation | The phone still has Hermes 0.3.3 (6). Its configuration was inspected read-only; its outbox and Keychain were not accessed. No app was uninstalled or replaced. |
| Signed build | Blocked by missing current provisioning profiles. All recovered matching profiles expired September 4, 2026; they match the existing Team, certificate and already paired devices. |
| Profile refresh | Xcode reports invalid saved account credentials / missing username; its account list is empty. No account token or password was extracted, entered or changed. |
| Install | Not attempted with an unsigned/expired build. The currently installed apps and data are preserved. |
| Xcode GUI | The Mac is locked and native UI access failed. Opening the project and selecting the physical Watch in Xcode cannot be claimed yet. No further UI retries are needed until it is unlocked. |

Personal account, Team, certificate/profile and device identifiers, endpoint metadata, raw logs, and resume commands remain in ignored local storage. Public evidence intentionally omits those identifiers.

The sanitized [setup results](verification/2026-10-25/SETUP_RESULTS.json) record these checks separately from the original implementation test run.

## The required human action

Unlock the Mac mini and sign back into the existing Apple account in **Xcode → Settings → Accounts**, completing any Apple 2FA yourself. The account must be the one associated with the already resolved personal Team. Creating a new identity or selecting a new Team is not the next step.

After that, the executor can renew the normal development profiles for the unchanged app IDs using the existing identity, build a signed candidate, verify its embedded profiles/signatures, and install it onto the existing pair without deleting app data. The intended GUI run selection is **HermesCaptureWatch → the paired physical Watch**. Selection and installation must be read back before claiming the setup is finished.

The private `.private/setup/RESUME.json` records the resolved destinations, build/install commands and project path for resumption. It contains no secret values and is not part of the repository. No generic signing checklist or new project is needed.

## App installation versus usable live actions

A normal-TLS, unauthenticated read of the existing configured backend returned HTTP 200 with only `aura.grocery_capture` enabled. The private endpoint was obtained from the installed app's preferences; no captures, Keychain secret or financial records were read.

Therefore installing this candidate does not make all three live actions ready. The exact external Aura adapter is not available in the reviewed source, reminder alert delivery is unverified, and the deployed backend has not enabled reminders or expenses. The [separate rollout proposal](MVP_BACKEND_ROLLOUT_PROPOSAL.md) specifies the smallest missing source handoff and deployment sequence. No production setting was changed.
