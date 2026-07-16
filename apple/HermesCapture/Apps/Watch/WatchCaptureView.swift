import SwiftUI
import WatchKit
import HermesCore

struct WatchCaptureView: View {
    let action: QuickActionKind

    @AppStorage("hermes.pseudonymousDeviceID") private var deviceID = ""
    @State private var text = ""
    @State private var statusMessage: String?
    @State private var isSaving = false

    private let accent = Color(red: 187 / 255, green: 0, blue: 14 / 255)

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Label(action.title, systemImage: action.symbolName)
                    .font(.headline)
                    .foregroundStyle(accent)

                TextField(prompt, text: $text)
                    .textInputAutocapitalization(.sentences)
                    .submitLabel(.done)

                Button {
                    Task { @MainActor in
                        await saveAndSend()
                    }
                } label: {
                    if isSaving {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Enviar", systemImage: "paperplane.fill")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(accent)
                .disabled(trimmedText.isEmpty || isSaving)

                if let statusMessage {
                    Text(statusMessage)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 4)
        }
        .navigationTitle(action.title)
        .onAppear {
            ensureDeviceIdentity()
        }
    }

    private var trimmedText: String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var prompt: String {
        switch action {
        case .expense:
            return "Ej. 45 mil en Uber"
        case .reminder:
            return "¿Qué recordar?"
        case .grocery:
            return "¿Qué falta?"
        case .general:
            return "Dile algo a Hermes"
        }
    }

    @MainActor
    private func saveAndSend() async {
        guard !trimmedText.isEmpty else { return }
        ensureDeviceIdentity()
        isSaving = true
        statusMessage = nil

        let factory = CaptureFactory(
            appVersion: appVersion,
            platform: "watchOS",
            osVersion: ProcessInfo.processInfo.operatingSystemVersionString,
            deviceID: deviceID,
            surface: "watch_app",
            nowISO8601: {
                ISO8601DateFormatter().string(from: Date())
            },
            makeRequestID: {
                UUID().uuidString.lowercased()
            }
        )
        let payload = factory.makePayload(
            kind: action,
            text: trimmedText
        )
        let outbox = FileOutboxStore(fileURL: outboxURL)

        do {
            _ = try await outbox.enqueue(payload, now: payload.createdAt)
            text = ""
            statusMessage = "Enviando · dry-run"

            guard
                let rawBaseURL = UserDefaults.standard.string(forKey: "hermes.baseURL"),
                let baseURL = try? EndpointValidator.normalizedBaseURL(from: rawBaseURL),
                let secret = try KeychainRouteSecretStore().loadRouteSecretSynchronously(),
                !secret.isEmpty
            else {
                statusMessage = "Guardado · configura desde iPhone"
                WKInterfaceDevice.current().play(.notification)
                isSaving = false
                return
            }

            let client = WebhookClient(
                endpoint: EndpointValidator.captureURL(from: baseURL)
            )
            let delivery = OutboxDeliveryService(
                store: outbox,
                client: client
            )
            let response = try await delivery.deliver(
                payload: payload,
                secret: secret
            )

            statusMessage = response.displayMessage ?? "Enviado · dry-run"
            WKInterfaceDevice.current().play(.success)
        } catch let failure as OutboxDeliveryFailure {
            statusMessage = failure.localizedDescription
            WKInterfaceDevice.current().play(.failure)
        } catch {
            statusMessage = "No se pudo guardar"
            WKInterfaceDevice.current().play(.failure)
        }

        isSaving = false
    }

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
    }

    private var outboxURL: URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return root
            .appendingPathComponent("HermesCapture", isDirectory: true)
            .appendingPathComponent("outbox.json", isDirectory: false)
    }

    private func ensureDeviceIdentity() {
        if deviceID.isEmpty {
            deviceID = "watch-\(UUID().uuidString.lowercased())"
        }
    }
}

#Preview {
    NavigationStack {
        WatchCaptureView(action: .expense)
    }
}
