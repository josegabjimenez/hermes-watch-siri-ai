# Physical-device setup · 25 October 2026

Jose requested Xcode setup so that he only needs to test Hermes on his Watch. This continues PR #1 and the existing candidate; it does not authorize merging or deploying the backend.

## Configured locally

The generated project is `apple/HermesCapture/HermesCapture.xcodeproj`. Both product targets reference `Config/Signing.xcconfig`, which optionally includes the ignored `Signing.xcconfig.local` in that directory. The local file supplies the existing personal development Team and the standard `Apple Development` identity selector. Automatic signing remains enabled, the bundle IDs and companion relationship are unchanged, and regenerating the Xcode project preserves this setup.

The Team was resolved from the recovered project and independently matched to the current Apple Development certificate. There is no Team choice left for Jose to make. The existing certificate is valid through August 19, 2027. No new identity, certificate or device registration was created.

## Actual device/build state

| Item | Verified state |
| --- | --- |
| Toolchain | Installed Xcode 27.0 (27A5237l), command-scoped `DEVELOPER_DIR`; global selection unchanged. |
| iPhone | Existing paired physical phone, iOS 27.2; Developer Mode enabled; available as an iOS build destination over the local network. |
| Apple Watch | Existing paired physical Watch, watchOS 27.0; Developer Mode enabled; available as a watchOS build destination. |
| Schemes | `HermesCaptureiOS` builds the companion with embedded Watch; `HermesCaptureWatch` targets the physical Watch. Both generated launch actions point to the corresponding app. |
| Local configuration check | Both schemes inherit the resolved Team and automatic signing, with no manual provisioning-profile override. A certificate fingerprint pin was rejected by Xcode under Automatic signing; restoring its standard `Apple Development` selector resolved the conflict. |
| Signed build | **Passed**, iOS with embedded Watch, from source commit `be43c532332a667ed6b20e44dce2ac8bac181616`. No implementation source changed during this resumed setup. |
| Signature/profile verification | Both bundles pass strict/deep codesign verification, reuse the original existing certificate, match the unchanged Team and bundle IDs, and contain their corresponding paired device in the renewed profile. Both contain the privacy manifest with tracking disabled. |
| Profile refresh | **Resolved** after Jose signed into the existing account. Automatic provisioning renewed profiles using the original certificate; no new identity/certificate was created. Both profiles expire November 1, 2026, at approximately 15:05 America/Bogota. |
| iPhone install | **Succeeded** as an in-place update. CoreDevice readback confirms Hermes **0.3.4 (7)**. No uninstall or app-data deletion was performed. |
| iPhone launch | Initially denied by iOS with a signature/entitlement/developer-trust error. After Jose confirmed trusting the existing developer profile, normal launch succeeded and a running Hermes process was read back. No capture/retry/confirmation action was invoked. |
| Watch install | Direct installation remains blocked by its Bluetooth tunnel. Earlier attempts returned CoreDevice 4000 / RemotePairing 1035, “The device rejected the Bluetooth connection attempt.” After destination refresh, a successful normal pairing-refresh command, and confirmation that both devices were unlocked nearby, the final attempt returned CoreDevice 4 / RemotePairing 1007: Bluetooth invalidated before tunnel creation, with an L2CAP open-channel failure. No device was unpaired or erased. Installation through the companion phone is awaiting physical readback. |
| Xcode GUI | Jose confirmed the Mac is unlocked. Native Xcode/Finder UI access still timed out; opening the project and selecting the physical Watch in the visible GUI remain **unverified**. No shell UI automation or private UI-state editing was used. |

Personal account, Team, certificate/profile and device identifiers, endpoint metadata, raw logs, and resume commands remain in ignored local storage. Public evidence intentionally omits those identifiers.

The sanitized [setup results](verification/2026-10-25/SETUP_RESULTS.json) record these checks separately from the original implementation test run.

## Remaining Watch check

Apple login, profile renewal, iPhone installation and iPhone developer trust are resolved. They do not need repeating.

The installed iPhone app includes the signed Watch app. The next physical check is the iPhone's **Watch → My Watch → Apps** list: if Hermes appears under Available Apps, tap Install, then open Hermes on the Watch without submitting a capture. Apple's [companion-app installation instructions](https://support.apple.com/en-ie/109023) describe this path. Whether the Watch actually installs/opens this candidate must be reported before claiming completion; the Mac's connection failure alone cannot establish that.

If the companion installation also fails, inspect the existing Watch connection in **Xcode → Window → Devices and Simulators** with the paired phone connected. The intended run selection is **HermesCaptureWatch → the paired physical Watch**. Do not erase/unpair either device as a troubleshooting shortcut. Apple's [device-run instructions](https://help.apple.com/xcode/mac/current/en.lproj/dev5a825a1ca.html) cover the paired-phone connection and Watch run destination.

The private `.private/setup/RESUME.json` records the resolved destinations, build/install commands and project path for resumption. Raw device/signing logs remain private. The development profiles require renewal after their actual expiry.

## App installation versus usable live actions

A normal-TLS, unauthenticated read of the existing configured backend returned HTTP 200 with only `aura.grocery_capture` enabled. The private endpoint was obtained from the installed app's preferences; no captures, Keychain secret or financial records were read.

Therefore installing this candidate does not make all three live actions ready. The exact external Aura adapter is not available in the reviewed source, reminder alert delivery is unverified, and the deployed backend has not enabled reminders or expenses. The [separate rollout proposal](MVP_BACKEND_ROLLOUT_PROPOSAL.md) specifies the smallest missing source handoff and deployment sequence. No production setting was changed.
