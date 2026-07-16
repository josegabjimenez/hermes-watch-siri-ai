import Combine
import Foundation
import HermesCore
import WatchConnectivity

final class WatchBootstrapReceiver: NSObject, ObservableObject {
    @Published private(set) var isConfigured = false
    @Published private(set) var statusMessage = "Configura desde el iPhone"

    private let secretStore = KeychainRouteSecretStore()
    private var session: WCSession?

    override init() {
        super.init()
        refreshStoredConfigurationStatus()

        guard WCSession.isSupported() else {
            statusMessage = "WatchConnectivity no disponible"
            return
        }
        let session = WCSession.default
        self.session = session
        session.delegate = self
        session.activate()
    }

    private func refreshStoredConfigurationStatus() {
        let endpoint = UserDefaults.standard.string(forKey: "hermes.baseURL") ?? ""
        let secret = try? secretStore.loadRouteSecretSynchronously()
        isConfigured = !endpoint.isEmpty && !(secret ?? "").isEmpty
        statusMessage = isConfigured ? "Configuración segura lista" : "Configura desde el iPhone"
    }

    private func updateStatus(configured: Bool, message: String) {
        DispatchQueue.main.async { [weak self] in
            self?.isConfigured = configured
            self?.statusMessage = message
        }
    }
}

extension WatchBootstrapReceiver: WCSessionDelegate {
    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        if let error {
            updateStatus(configured: isConfigured, message: "WatchConnectivity: \(error.localizedDescription)")
        }
    }

    func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        guard message[WatchBootstrapMessage.commandKey] as? String == WatchBootstrapMessage.command else {
            replyHandler([
                WatchBootstrapMessage.replyOKKey: false,
                WatchBootstrapMessage.replyErrorKey: "unsupported_command"
            ])
            return
        }
        guard
            let rawBaseURL = message[WatchBootstrapMessage.baseURLKey] as? String,
            let routeSecret = message[WatchBootstrapMessage.routeSecretKey] as? String,
            !routeSecret.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            replyHandler([
                WatchBootstrapMessage.replyOKKey: false,
                WatchBootstrapMessage.replyErrorKey: "invalid_payload"
            ])
            return
        }

        do {
            let baseURL = try EndpointValidator.normalizedBaseURL(from: rawBaseURL)
            try secretStore.saveRouteSecretSynchronously(
                routeSecret.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            UserDefaults.standard.set(baseURL.absoluteString, forKey: "hermes.baseURL")
            updateStatus(configured: true, message: "Configuración segura lista")
            replyHandler([WatchBootstrapMessage.replyOKKey: true])
        } catch {
            updateStatus(configured: false, message: "No se pudo guardar configuración")
            replyHandler([
                WatchBootstrapMessage.replyOKKey: false,
                WatchBootstrapMessage.replyErrorKey: "secure_storage_failed"
            ])
        }
    }
}
