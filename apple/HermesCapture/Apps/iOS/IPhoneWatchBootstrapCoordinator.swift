import Combine
import Foundation
import WatchConnectivity

final class IPhoneWatchBootstrapCoordinator: NSObject, ObservableObject {
    @Published private(set) var isReachable = false
    @Published private(set) var activationMessage = "Activando WatchConnectivity"

    private var session: WCSession?

    override init() {
        super.init()
        guard WCSession.isSupported() else {
            activationMessage = "WatchConnectivity no disponible"
            return
        }
        let session = WCSession.default
        self.session = session
        session.delegate = self
        session.activate()
    }

    func sendConfiguration(
        baseURL: URL,
        routeSecret: String,
        completion: @escaping (Result<Void, WatchBootstrapSendError>) -> Void
    ) {
        guard let session else {
            completion(.failure(.unsupported))
            return
        }
        guard session.isReachable else {
            refreshReachability(session)
            completion(.failure(.watchNotReachable))
            return
        }

        let message = WatchBootstrapMessage.make(
            baseURL: baseURL,
            routeSecret: routeSecret
        )
        session.sendMessage(message) { reply in
            DispatchQueue.main.async {
                if reply[WatchBootstrapMessage.replyOKKey] as? Bool == true {
                    completion(.success(()))
                } else {
                    completion(.failure(.watchRejected))
                }
            }
        } errorHandler: { _ in
            DispatchQueue.main.async {
                completion(.failure(.deliveryFailed))
            }
        }
    }

    private func refreshReachability(_ session: WCSession) {
        DispatchQueue.main.async { [weak self] in
            self?.isReachable = session.isReachable
            self?.activationMessage = session.isReachable
                ? "Apple Watch conectado"
                : "Abre Hermes en el Apple Watch"
        }
    }
}

extension IPhoneWatchBootstrapCoordinator: WCSessionDelegate {
    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        DispatchQueue.main.async { [weak self] in
            if let error {
                self?.isReachable = false
                self?.activationMessage = "WatchConnectivity: \(error.localizedDescription)"
            } else {
                self?.isReachable = session.isReachable
                self?.activationMessage = session.isReachable
                    ? "Apple Watch conectado"
                    : "Abre Hermes en el Apple Watch"
            }
        }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        refreshReachability(session)
    }

    func sessionDidBecomeInactive(_ session: WCSession) {
        refreshReachability(session)
    }

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
}

enum WatchBootstrapSendError: LocalizedError {
    case unsupported
    case watchNotReachable
    case watchRejected
    case deliveryFailed

    var errorDescription: String? {
        switch self {
        case .unsupported:
            return "WatchConnectivity no está disponible"
        case .watchNotReachable:
            return "Abre Hermes en el Apple Watch y vuelve a intentar"
        case .watchRejected:
            return "El Apple Watch rechazó la configuración"
        case .deliveryFailed:
            return "No se pudo entregar la configuración al Apple Watch"
        }
    }
}
