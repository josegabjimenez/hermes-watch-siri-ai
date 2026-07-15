import XCTest
@testable import HermesCore

final class HermesCoreTests: XCTestCase {
    func testPayloadEncodingUsesMobileCaptureContractKeys() throws {
        let payload = CapturePayloadV1(
            requestID: "unit-request-1",
            createdAt: "2026-07-06T20:55:00Z",
            source: CaptureSource(
                appVersion: "0.1.0",
                platform: "watchOS",
                osVersion: "10.0",
                deviceID: "unit-device",
                surface: "watch_app"
            ),
            route: .expense,
            capture: CaptureText(modality: "watch_dictation", text: "45 mil en Uber"),
            entities: CaptureEntities(currency: "COP"),
            context: CaptureContext(dryRun: true, allowWrite: false)
        )

        let data = try JSONEncoder.hermesCaptureEncoder().encode(payload)
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))

        XCTAssertTrue(json.contains("\"event_type\":\"mobile_capture.v1\""))
        XCTAssertTrue(json.contains("\"schema_version\":1"))
        XCTAssertTrue(json.contains("\"request_id\":\"unit-request-1\""))
        XCTAssertTrue(json.contains("\"app_version\":\"0.1.0\""))
        XCTAssertTrue(json.contains("\"device_id\":\"unit-device\""))
        XCTAssertTrue(json.contains("\"raw_text\":\"45 mil en Uber\""))
        XCTAssertTrue(json.contains("\"dry_run\":true"))
        XCTAssertTrue(json.contains("\"allow_write\":false"))
    }

    func testHMACV2KnownVector() {
        let body = Data(#"{"event_type":"mobile_capture.v1","request_id":"unit-test"}"#.utf8)
        let signature = HMACSigner.signatureV2(
            rawBody: body,
            timestamp: "1700000000",
            secret: "test-secret"
        )

        XCTAssertEqual(signature, "e824cb05567e5cae90d3eede3f35c5ca69fb2a8c1ced969456145a4f6b251aab")
    }

    func testWebhookRequestContainsRequiredHeaders() throws {
        let payload = CapturePayloadV1(
            requestID: "unit-request-2",
            createdAt: "2026-07-06T20:55:00Z",
            source: CaptureSource(
                appVersion: "0.1.0",
                platform: "watchOS",
                osVersion: "10.0",
                deviceID: "unit-device",
                surface: "watch_app"
            ),
            route: .reminder,
            capture: CaptureText(
                modality: "watch_dictation",
                text: "mañana a las dos llamar a mamá"
            )
        )
        let endpoint = try XCTUnwrap(URL(string: "https://example.invalid/webhooks/mobile-capture-v1"))
        let client = WebhookClient(endpoint: endpoint)
        let request = try client.makeRequest(
            payload: payload,
            secret: "test-secret",
            timestamp: "1700000000"
        )

        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: WebhookHeaders.timestamp), "1700000000")
        XCTAssertNotNil(request.value(forHTTPHeaderField: WebhookHeaders.signatureV2))
        XCTAssertEqual(request.value(forHTTPHeaderField: WebhookHeaders.requestID), "unit-request-2")
        XCTAssertEqual(request.value(forHTTPHeaderField: WebhookHeaders.payloadVersion), "1")
        XCTAssertEqual(request.value(forHTTPHeaderField: WebhookHeaders.deviceID), "unit-device")
    }

    func testCaptureFactoryCreatesDryRunPayload() {
        let factory = CaptureFactory(
            appVersion: "0.1.0",
            platform: "watchOS",
            osVersion: "10.0",
            deviceID: "unit-device",
            surface: "watch_app",
            nowISO8601: { "2026-07-06T20:55:00Z" },
            makeRequestID: { "factory-request" }
        )

        let payload = factory.makePayload(
            kind: .grocery,
            text: "agrega leche al mercado"
        )

        XCTAssertEqual(payload.requestID, "factory-request")
        XCTAssertEqual(payload.route.domain, .auraGroceryCapture)
        XCTAssertEqual(payload.context.dryRun, true)
        XCTAssertEqual(payload.context.allowWrite, false)
    }

    func testFileOutboxPersistsAndDeduplicatesRequestID() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let fileURL = directory.appendingPathComponent("outbox.json")
        defer { try? FileManager.default.removeItem(at: directory) }

        let payload = CapturePayloadV1(
            requestID: "outbox-request-1",
            createdAt: "2026-07-13T20:00:00Z",
            source: CaptureSource(
                appVersion: "0.1.0",
                platform: "watchOS",
                osVersion: "26.5",
                deviceID: "unit-device",
                surface: "watch_app"
            ),
            route: .expense,
            capture: CaptureText(modality: "watch_dictation", text: "45 mil en Uber")
        )
        let store = FileOutboxStore(fileURL: fileURL)

        let first = try await store.enqueue(payload, now: payload.createdAt)
        let duplicate = try await store.enqueue(payload, now: payload.createdAt)
        var items = try await store.loadAll()

        XCTAssertEqual(first.id, "outbox-request-1")
        XCTAssertEqual(duplicate.id, first.id)
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.status, .pending)

        try await store.markSending(requestID: payload.requestID, now: "2026-07-13T20:00:01Z")
        try await store.markSent(requestID: payload.requestID, now: "2026-07-13T20:00:02Z")
        items = try await store.loadAll()

        XCTAssertEqual(items.first?.status, .sent)
        XCTAssertEqual(items.first?.attempts, 1)
        XCTAssertNil(items.first?.lastError)
    }

    func testEndpointValidatorRequiresHTTPSAndBuildsHealthURL() throws {
        let baseURL = try EndpointValidator.normalizedBaseURL(
            from: "  https://example.ts.net:8650/  "
        )

        XCTAssertEqual(baseURL.absoluteString, "https://example.ts.net:8650")
        XCTAssertEqual(
            EndpointValidator.healthURL(from: baseURL).absoluteString,
            "https://example.ts.net:8650/health"
        )
        XCTAssertThrowsError(
            try EndpointValidator.normalizedBaseURL(from: "http://example.ts.net:8650")
        ) { error in
            XCTAssertEqual(error as? EndpointValidationError, .httpsRequired)
        }
        XCTAssertThrowsError(
            try EndpointValidator.normalizedBaseURL(from: "https://100.64.0.1:8650")
        ) { error in
            XCTAssertEqual(error as? EndpointValidationError, .dnsNameRequired)
        }
    }
}
