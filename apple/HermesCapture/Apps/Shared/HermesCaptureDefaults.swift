import Foundation

// Shared app-level constants for iOS/watchOS shells.
// Keep secrets out of this file; endpoint can be edited in Debug UI and synced from iPhone to Watch.
enum HermesCaptureDefaults {
    static let placeholderBaseURL = "https://<TAILSCALE_DNS_NAME>:8650"
    static let endpointPath = "/webhooks/mobile-capture-v1"
}
