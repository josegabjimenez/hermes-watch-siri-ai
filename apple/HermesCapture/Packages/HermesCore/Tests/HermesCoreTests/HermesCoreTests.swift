import Foundation
import Testing
@testable import HermesCore

@Suite("HermesCore")
struct HermesCoreTests {
    @Test("Payload encoding uses mobile_capture.v1 contract keys")
    func payloadEncodingUsesMobileCaptureContractKeys() throws {
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
        let json = try #require(String(data: data, encoding: .utf8))

        #expect(json.contains("\"event_type\":\"mobile_capture.v1\""))
        #expect(json.contains("\"schema_version\":1"))
        #expect(json.contains("\"request_id\":\"unit-request-1\""))
        #expect(json.contains("\"app_version\":\"0.1.0\""))
        #expect(json.contains("\"device_id\":\"unit-device\""))
        #expect(json.contains("\"raw_text\":\"45 mil en Uber\""))
        #expect(json.contains("\"dry_run\":true"))
        #expect(json.contains("\"allow_write\":false"))
    }

    @Test("HMAC V2 matches the known vector")
    func hmacV2KnownVector() {
        let body = Data(#"{"event_type":"mobile_capture.v1","request_id":"unit-test"}"#.utf8)
        let signature = HMACSigner.signatureV2(
            rawBody: body,
            timestamp: "1700000000",
            secret: "test-secret"
        )

        #expect(signature == "e824cb05567e5cae90d3eede3f35c5ca69fb2a8c1ced969456145a4f6b251aab")
    }

    @Test("Webhook request contains all required headers")
    func webhookRequestContainsRequiredHeaders() throws {
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
        let endpoint = try #require(URL(string: "https://example.invalid/webhooks/mobile-capture-v1"))
        let client = WebhookClient(endpoint: endpoint)
        let request = try client.makeRequest(
            payload: payload,
            secret: "test-secret",
            timestamp: "1700000000"
        )

        #expect(request.httpMethod == "POST")
        #expect(request.value(forHTTPHeaderField: WebhookHeaders.timestamp) == "1700000000")
        #expect(request.value(forHTTPHeaderField: WebhookHeaders.signatureV2) != nil)
        #expect(request.value(forHTTPHeaderField: WebhookHeaders.requestID) == "unit-request-2")
        #expect(request.value(forHTTPHeaderField: WebhookHeaders.payloadVersion) == "1")
        #expect(request.value(forHTTPHeaderField: WebhookHeaders.deviceID) == "unit-device")
    }

    @Test("Capture factory creates dry-run payload")
    func captureFactoryCreatesDryRunPayload() {
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

        #expect(payload.requestID == "factory-request")
        #expect(payload.route.domain == .auraGroceryCapture)
        #expect(payload.context.dryRun == true)
        #expect(payload.context.allowWrite == false)
    }
}
