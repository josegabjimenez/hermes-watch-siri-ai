import SwiftUI
import HermesCore

struct WatchContentView: View {
    @EnvironmentObject private var bootstrapReceiver: WatchBootstrapReceiver
    @State private var isRetrying = false
    @State private var retryMessage: String?

    private let actions: [QuickActionKind] = [.expense, .reminder, .grocery, .general]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(actions) { action in
                        NavigationLink {
                            WatchCaptureView(action: action)
                        } label: {
                            Label(action.title, systemImage: action.symbolName)
                        }
                    }

                    NavigationLink {
                        WatchHistoryView()
                    } label: {
                        Label("Historial", systemImage: "clock.arrow.circlepath")
                    }
                }

                Section {
                    Label(
                        bootstrapReceiver.statusMessage,
                        systemImage: bootstrapReceiver.isConfigured ? "checkmark.shield" : "iphone.gen3"
                    )
                    .font(.footnote)
                    .foregroundStyle(bootstrapReceiver.isConfigured ? .green : .secondary)

                    if bootstrapReceiver.isConfigured {
                        Button {
                            Task { @MainActor in
                                await retryPendingCaptures()
                            }
                        } label: {
                            if isRetrying {
                                ProgressView()
                            } else {
                                Label("Reintentar pendientes", systemImage: "arrow.clockwise")
                            }
                        }
                        .disabled(isRetrying)
                    }

                    if let retryMessage {
                        Text(retryMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Hermes")
        }
    }

    @MainActor
    private func retryPendingCaptures() async {
        isRetrying = true
        defer { isRetrying = false }

        guard
            let rawBaseURL = UserDefaults.standard.string(forKey: "hermes.baseURL"),
            let baseURL = try? EndpointValidator.normalizedBaseURL(from: rawBaseURL),
            let secret = try? KeychainRouteSecretStore().loadRouteSecretSynchronously(),
            !secret.isEmpty
        else {
            retryMessage = "Configura desde el iPhone"
            return
        }

        let store = FileOutboxStore(fileURL: outboxURL)
        do {
            let items = try await store.loadDeliverable()
            guard !items.isEmpty else {
                retryMessage = "Sin pendientes"
                return
            }

            let delivery = OutboxDeliveryService(
                store: store,
                client: WebhookClient(endpoint: EndpointValidator.captureURL(from: baseURL))
            )
            var sent = 0
            var failed = 0

            for item in items {
                do {
                    _ = try await delivery.deliver(
                        payload: item.payload,
                        secret: secret
                    )
                    sent += 1
                } catch {
                    failed += 1
                }
            }

            retryMessage = failed == 0
                ? "\(sent) enviado(s) · dry-run"
                : "\(sent) enviados · \(failed) pendientes"
        } catch {
            retryMessage = "No se pudo leer outbox"
        }
    }

    private var outboxURL: URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return root
            .appendingPathComponent("HermesCapture", isDirectory: true)
            .appendingPathComponent("outbox.json", isDirectory: false)
    }
}

#Preview {
    WatchContentView()
        .environmentObject(WatchBootstrapReceiver())
}
