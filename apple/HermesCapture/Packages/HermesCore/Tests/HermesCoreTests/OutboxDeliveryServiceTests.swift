import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import HermesCore

final class OutboxDeliveryServiceTests: XCTestCase {
    func testSuccessfulDeliveryMarksItemSent() async throws {
        let fixture = try await makeFixture(requestID: "delivery-success")
        defer { try? FileManager.default.removeItem(at: fixture.directory) }

        let responseBody = Data("""
        {
          "status":"accepted",
          "dry_run":true,
          "request_id":"delivery-success",
          "domain":"argos.general_capture",
          "display_message":"Captura validada · dry-run ✅",
          "plan":{"would_write":false,"side_effects":[]}
        }
        """.utf8)
        let session = URLSessionStub { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertNotNil(request.value(forHTTPHeaderField: WebhookHeaders.signatureV2))
            XCTAssertEqual(request.value(forHTTPHeaderField: WebhookHeaders.requestID), "delivery-success")
            let response = try XCTUnwrap(
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )
            )
            return (responseBody, response)
        }
        let client = WebhookClient(
            endpoint: URL(string: "https://example.invalid/webhooks/mobile-capture-v1")!,
            session: session
        )
        let delivery = OutboxDeliveryService(
            store: fixture.store,
            client: client,
            nowISO8601: { "2026-07-13T22:00:01Z" }
        )

        let response = try await delivery.deliver(
            payload: fixture.payload,
            secret: "unit-test-secret"
        )
        let items = try await fixture.store.loadAll()

        XCTAssertEqual(response.displayMessage, "Captura validada · dry-run ✅")
        XCTAssertEqual(items.first?.status, .sent)
        XCTAssertEqual(items.first?.attempts, 1)
        XCTAssertNil(items.first?.lastError)
    }

    func testHTTPFailureStoresOnlySanitizedCode() async throws {
        let fixture = try await makeFixture(requestID: "delivery-unauthorized")
        defer { try? FileManager.default.removeItem(at: fixture.directory) }

        let session = URLSessionStub { request in
            let response = try XCTUnwrap(
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 401,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )
            )
            return (Data(#"{"error":"body-must-not-enter-outbox"}"#.utf8), response)
        }
        let client = WebhookClient(
            endpoint: URL(string: "https://example.invalid/webhooks/mobile-capture-v1")!,
            session: session
        )
        let delivery = OutboxDeliveryService(
            store: fixture.store,
            client: client,
            nowISO8601: { "2026-07-13T22:00:01Z" }
        )

        do {
            _ = try await delivery.deliver(
                payload: fixture.payload,
                secret: "wrong-secret"
            )
            XCTFail("Expected HTTP 401 failure")
        } catch let failure as OutboxDeliveryFailure {
            XCTAssertEqual(failure, .http(401))
        }

        let items = try await fixture.store.loadAll()
        XCTAssertEqual(items.first?.status, .failed)
        XCTAssertEqual(items.first?.attempts, 1)
        XCTAssertEqual(items.first?.lastError, "http_401")
        XCTAssertFalse(items.first?.lastError?.contains("body-must-not-enter-outbox") ?? true)
        let deliverableItems = try await fixture.store.loadDeliverable()
        XCTAssertEqual(deliverableItems.count, 1)
    }

    func testNetworkFailureRetriesSameRequestIDAndMarksSent() async throws {
        let fixture = try await makeFixture(requestID: "delivery-retry")
        defer { try? FileManager.default.removeItem(at: fixture.directory) }

        let failingClient = WebhookClient(
            endpoint: URL(string: "https://example.invalid/webhooks/mobile-capture-v1")!,
            session: URLSessionStub { _ in
                throw URLError(.notConnectedToInternet)
            }
        )
        let firstAttempt = OutboxDeliveryService(
            store: fixture.store,
            client: failingClient,
            nowISO8601: { "2026-07-13T22:00:01Z" }
        )

        do {
            _ = try await firstAttempt.deliver(
                payload: fixture.payload,
                secret: "unit-test-secret"
            )
            XCTFail("Expected network failure")
        } catch let failure as OutboxDeliveryFailure {
            XCTAssertEqual(failure, .network(URLError.notConnectedToInternet.rawValue))
        }

        var items = try await fixture.store.loadAll()
        XCTAssertEqual(items.first?.status, .failed)
        XCTAssertEqual(items.first?.attempts, 1)
        XCTAssertEqual(items.first?.payload.requestID, "delivery-retry")

        let responseBody = Data("""
        {
          "status":"accepted",
          "dry_run":true,
          "request_id":"delivery-retry",
          "domain":"argos.general_capture",
          "display_message":"Captura validada · dry-run ✅",
          "plan":{"would_write":false,"side_effects":[]}
        }
        """.utf8)
        let successClient = WebhookClient(
            endpoint: URL(string: "https://example.invalid/webhooks/mobile-capture-v1")!,
            session: URLSessionStub { request in
                XCTAssertEqual(
                    request.value(forHTTPHeaderField: WebhookHeaders.requestID),
                    "delivery-retry"
                )
                let response = try XCTUnwrap(
                    HTTPURLResponse(
                        url: request.url!,
                        statusCode: 200,
                        httpVersion: nil,
                        headerFields: ["Content-Type": "application/json"]
                    )
                )
                return (responseBody, response)
            }
        )
        let retry = OutboxDeliveryService(
            store: fixture.store,
            client: successClient,
            nowISO8601: { "2026-07-13T22:00:02Z" }
        )

        _ = try await retry.deliver(
            payload: fixture.payload,
            secret: "unit-test-secret"
        )

        items = try await fixture.store.loadAll()
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.status, .sent)
        XCTAssertEqual(items.first?.attempts, 2)
        XCTAssertNil(items.first?.lastError)
        let remaining = try await fixture.store.loadDeliverable()
        XCTAssertTrue(remaining.isEmpty)
    }

    private func makeFixture(requestID: String) async throws -> DeliveryFixture {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let fileURL = directory.appendingPathComponent("outbox.json")
        let payload = CapturePayloadV1(
            requestID: requestID,
            createdAt: "2026-07-13T22:00:00Z",
            source: CaptureSource(
                appVersion: "0.1.0",
                platform: "watchOS",
                osVersion: "26.5",
                deviceID: "unit-device",
                surface: "watch_app"
            ),
            route: .general,
            capture: CaptureText(
                modality: "watch_dictation",
                text: "integration test"
            )
        )
        let store = FileOutboxStore(fileURL: fileURL)
        _ = try await store.enqueue(payload, now: payload.createdAt)
        return DeliveryFixture(
            directory: directory,
            payload: payload,
            store: store
        )
    }
}

private struct DeliveryFixture {
    let directory: URL
    let payload: CapturePayloadV1
    let store: FileOutboxStore
}

private final class URLSessionStub: URLSessioning {
    typealias Handler = (URLRequest) throws -> (Data, URLResponse)
    private let handler: Handler

    init(handler: @escaping Handler) {
        self.handler = handler
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try handler(request)
    }
}
