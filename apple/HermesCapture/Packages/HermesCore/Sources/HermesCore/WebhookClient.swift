import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum WebhookClientError: Error, Equatable, Sendable {
    case invalidHTTPResponse
    case unacceptableStatus(Int, String)
}

public protocol URLSessioning: Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

extension URLSession: URLSessioning {}

public final class WebhookClient: @unchecked Sendable {
    private let endpoint: URL
    private let session: URLSessioning
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(
        endpoint: URL,
        session: URLSessioning = URLSession.shared,
        encoder: JSONEncoder = .hermesCaptureEncoder(),
        decoder: JSONDecoder = .hermesCaptureDecoder()
    ) {
        self.endpoint = endpoint
        self.session = session
        self.encoder = encoder
        self.decoder = decoder
    }

    public func makeRequest(payload: CapturePayloadV1, secret: String, timestamp: String = String(Int(Date().timeIntervalSince1970))) throws -> URLRequest {
        let signed = try WebhookRequestSigner.sign(payload: payload, secret: secret, timestamp: timestamp, encoder: encoder)
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.httpBody = signed.body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(signed.timestamp, forHTTPHeaderField: WebhookHeaders.timestamp)
        request.setValue(signed.signature, forHTTPHeaderField: WebhookHeaders.signatureV2)
        request.setValue(signed.requestID, forHTTPHeaderField: WebhookHeaders.requestID)
        request.setValue("1", forHTTPHeaderField: WebhookHeaders.payloadVersion)
        request.setValue(signed.client, forHTTPHeaderField: WebhookHeaders.client)
        request.setValue(signed.deviceID, forHTTPHeaderField: WebhookHeaders.deviceID)
        return request
    }

    public func submit(payload: CapturePayloadV1, secret: String) async throws -> CaptureResponseV1 {
        let request = try makeRequest(payload: payload, secret: secret)
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw WebhookClientError.invalidHTTPResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw WebhookClientError.unacceptableStatus(httpResponse.statusCode, body)
        }
        return try decoder.decode(CaptureResponseV1.self, from: data)
    }
}
