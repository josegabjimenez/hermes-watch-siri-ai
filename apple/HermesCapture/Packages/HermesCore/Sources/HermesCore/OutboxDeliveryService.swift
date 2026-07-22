import Foundation

public enum OutboxDeliveryFailure: Error, Equatable, LocalizedError, Sendable {
    case http(Int)
    case network(Int)
    case invalidResponse
    case unsafeResponse
    case unknown

    public var errorDescription: String? {
        switch self {
        case .http(401):
            return "HMAC rechazado · configura nuevamente desde el iPhone"
        case .http(let statusCode):
            return "El BFF respondió HTTP \(statusCode)"
        case .network:
            return "Sin conexión · guardado para reintento"
        case .invalidResponse:
            return "Respuesta inválida · guardado para reintento"
        case .unsafeResponse:
            return "Respuesta no segura · envío detenido"
        case .unknown:
            return "No se pudo enviar · guardado para reintento"
        }
    }

    public var isTransientTransportFailure: Bool {
        switch self {
        case .network:
            return true
        case .http(let statusCode):
            return statusCode == 502 || statusCode == 503 || statusCode == 504
        case .invalidResponse, .unsafeResponse, .unknown:
            return false
        }
    }

    public var storageCode: String {
        switch self {
        case .http(let statusCode):
            return "http_\(statusCode)"
        case .network(let code):
            return "network_\(code)"
        case .invalidResponse:
            return "invalid_response"
        case .unsafeResponse:
            return "unsafe_response"
        case .unknown:
            return "send_failed"
        }
    }
}

public actor OutboxDeliveryService {
    private let store: FileOutboxStore
    private let client: WebhookClient
    private let nowISO8601: @Sendable () -> String

    public init(
        store: FileOutboxStore,
        client: WebhookClient,
        nowISO8601: @escaping @Sendable () -> String = {
            ISO8601DateFormatter().string(from: Date())
        }
    ) {
        self.store = store
        self.client = client
        self.nowISO8601 = nowISO8601
    }

    public func deliver(
        payload: CapturePayloadV1,
        secret: String
    ) async throws -> CaptureResponseV1 {
        try await store.markSending(
            requestID: payload.requestID,
            now: nowISO8601()
        )

        do {
            #if DEBUG
            if ProcessInfo.processInfo.environment["HERMES_SIMULATE_OFFLINE"] == "1" {
                throw URLError(.notConnectedToInternet)
            }
            #endif
            let response = try await client.submit(payload: payload, secret: secret)
            guard response.dryRun == true, response.plan?.wouldWrite != true else {
                throw OutboxDeliveryFailure.unsafeResponse
            }
            try await store.markSent(
                requestID: payload.requestID,
                now: nowISO8601(),
                deliveryPath: .directHTTPS
            )
            return response
        } catch {
            let failure = Self.classify(error)
            try? await store.markFailed(
                requestID: payload.requestID,
                message: failure.storageCode,
                now: nowISO8601()
            )
            throw failure
        }
    }

    private static func classify(_ error: Error) -> OutboxDeliveryFailure {
        if let failure = error as? OutboxDeliveryFailure {
            return failure
        }
        if let clientError = error as? WebhookClientError {
            switch clientError {
            case .invalidHTTPResponse:
                return .invalidResponse
            case .unacceptableStatus(let statusCode, _):
                return .http(statusCode)
            }
        }
        if let urlError = error as? URLError {
            return .network(urlError.errorCode)
        }
        if error is DecodingError {
            return .invalidResponse
        }
        return .unknown
    }
}
