import Foundation

/// Ephemeral WatchConnectivity message contract.
/// The route secret must only travel via `sendMessage`, never application context
/// or user-info queues that can persist plaintext for deferred delivery.
enum WatchBootstrapMessage {
    static let commandKey = "command"
    static let command = "bootstrap_mobile_capture_v1"
    static let baseURLKey = "base_url"
    static let routeSecretKey = "route_secret"
    static let replyOKKey = "ok"
    static let replyErrorKey = "error"

    static func make(baseURL: URL, routeSecret: String) -> [String: Any] {
        [
            commandKey: command,
            baseURLKey: baseURL.absoluteString,
            routeSecretKey: routeSecret
        ]
    }
}
