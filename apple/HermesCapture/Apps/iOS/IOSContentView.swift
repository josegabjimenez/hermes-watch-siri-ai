import SwiftUI
import HermesCore

struct IOSContentView: View {
    @StateObject private var watchBootstrap = IPhoneWatchBootstrapCoordinator()

    @AppStorage("hermes.baseURL") private var savedBaseURL = ""
    @AppStorage("hermes.pseudonymousDeviceID") private var deviceID = ""
    @State private var endpointInput = ""
    @State private var secretInput = ""
    @State private var secretConfigured = false
    @State private var statusMessage: String?
    @State private var isSaving = false
    @State private var isTesting = false
    @State private var isTestingHMAC = false
    @State private var isSendingToWatch = false

    private let secretStore = KeychainRouteSecretStore()
    private let accent = Color(red: 187 / 255, green: 0, blue: 14 / 255)

    var body: some View {
        NavigationStack {
            Form {
                Section("BFF por Tailscale") {
                    TextField("https://<TAILSCALE_DNS_NAME>:8650", text: $endpointInput)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)

                    Button {
                        Task { @MainActor in
                            await testConnection()
                        }
                    } label: {
                        if isTesting {
                            ProgressView()
                        } else {
                            Label("Probar conexión", systemImage: "network")
                        }
                    }
                    .disabled(endpointInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isTesting)
                }

                Section("Autenticación") {
                    SecureField("Secreto HMAC de la ruta", text: $secretInput)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    HStack {
                        Label(
                            secretConfigured ? "Secreto configurado" : "Secreto pendiente",
                            systemImage: secretConfigured ? "checkmark.shield" : "exclamationmark.shield"
                        )
                        .foregroundStyle(secretConfigured ? .green : .secondary)
                        Spacer()
                    }

                    Button {
                        Task { @MainActor in
                            await saveConfiguration()
                        }
                    } label: {
                        if isSaving {
                            ProgressView()
                        } else {
                            Label("Guardar configuración", systemImage: "lock.shield")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(accent)
                    .disabled(isSaving)

                    Button {
                        Task { @MainActor in
                            await testHMAC()
                        }
                    } label: {
                        if isTestingHMAC {
                            ProgressView()
                        } else {
                            Label("Probar HMAC", systemImage: "checkmark.shield")
                        }
                    }
                    .disabled(!secretConfigured || savedBaseURL.isEmpty || isTestingHMAC)
                }

                Section("Apple Watch") {
                    Label(
                        watchBootstrap.activationMessage,
                        systemImage: watchBootstrap.isReachable ? "applewatch.radiowaves.left.and.right" : "applewatch.slash"
                    )
                    .foregroundStyle(watchBootstrap.isReachable ? .green : .secondary)

                    Button {
                        Task { @MainActor in
                            await sendConfigurationToWatch()
                        }
                    } label: {
                        if isSendingToWatch {
                            ProgressView()
                        } else {
                            Label("Enviar configuración al Watch", systemImage: "iphone.and.arrow.forward")
                        }
                    }
                    .disabled(!secretConfigured || !watchBootstrap.isReachable || isSendingToWatch)

                    Text("Abre Hermes en ambos simuladores. El secreto viaja solo en un mensaje interactivo y se guarda inmediatamente en Keychain del Watch.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if let statusMessage {
                    Section("Estado") {
                        Text(statusMessage)
                    }
                }
            }
            .navigationTitle("Hermes Capture")
            .onAppear {
                ensureDeviceIdentity()
                endpointInput = savedBaseURL
                Task { @MainActor in
                    await refreshSecretStatus()
                }
            }
        }
    }

    @MainActor
    private func saveConfiguration() async {
        isSaving = true
        defer { isSaving = false }

        do {
            let baseURL = try EndpointValidator.normalizedBaseURL(from: endpointInput)
            let secret = secretInput.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !secret.isEmpty else {
                statusMessage = "Ingresa el secreto HMAC"
                return
            }

            try await secretStore.saveRouteSecret(secret)
            savedBaseURL = baseURL.absoluteString
            endpointInput = baseURL.absoluteString
            secretInput = ""
            secretConfigured = true
            statusMessage = "Configuración guardada localmente"
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    @MainActor
    private func testConnection() async {
        isTesting = true
        defer { isTesting = false }

        do {
            let baseURL = try EndpointValidator.normalizedBaseURL(from: endpointInput)
            let healthURL = EndpointValidator.healthURL(from: baseURL)
            let (data, response) = try await URLSession.shared.data(from: healthURL)
            guard let httpResponse = response as? HTTPURLResponse else {
                statusMessage = "Respuesta HTTP inválida"
                return
            }
            guard (200..<300).contains(httpResponse.statusCode) else {
                statusMessage = "Health respondió HTTP \(httpResponse.statusCode)"
                return
            }

            let health = try? JSONDecoder().decode(BFFHealthResponse.self, from: data)
            statusMessage = health.map { "Conectado · \($0.mode ?? $0.status)" } ?? "Conectado · HTTP \(httpResponse.statusCode)"
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    @MainActor
    private func sendConfigurationToWatch() async {
        isSendingToWatch = true

        do {
            guard let secret = try await secretStore.loadRouteSecret(), !secret.isEmpty else {
                secretConfigured = false
                statusMessage = "Guarda primero el secreto HMAC"
                isSendingToWatch = false
                return
            }
            let baseURL = try EndpointValidator.normalizedBaseURL(from: savedBaseURL)
            watchBootstrap.sendConfiguration(baseURL: baseURL, routeSecret: secret) { result in
                isSendingToWatch = false
                switch result {
                case .success:
                    statusMessage = "Configuración segura enviada al Watch"
                case .failure(let error):
                    statusMessage = error.localizedDescription
                }
            }
        } catch {
            isSendingToWatch = false
            statusMessage = error.localizedDescription
        }
    }

    @MainActor
    private func testHMAC() async {
        isTestingHMAC = true
        defer { isTestingHMAC = false }

        do {
            guard let secret = try await secretStore.loadRouteSecret(), !secret.isEmpty else {
                secretConfigured = false
                statusMessage = "Guarda primero el secreto HMAC"
                return
            }

            ensureDeviceIdentity()
            let baseURL = try EndpointValidator.normalizedBaseURL(from: savedBaseURL)
            let factory = CaptureFactory(
                appVersion: appVersion,
                platform: "iOS",
                osVersion: ProcessInfo.processInfo.operatingSystemVersionString,
                deviceID: deviceID,
                surface: "iphone_app",
                nowISO8601: { ISO8601DateFormatter().string(from: Date()) },
                makeRequestID: { UUID().uuidString.lowercased() }
            )
            let payload = factory.makePayload(
                kind: .general,
                text: "HermesCapture HMAC connectivity check"
            )
            let client = WebhookClient(endpoint: EndpointValidator.captureURL(from: baseURL))
            let response = try await client.submit(payload: payload, secret: secret)

            guard response.dryRun == true, response.plan?.wouldWrite != true else {
                statusMessage = "Respuesta insegura: se esperaba dry-run"
                return
            }
            statusMessage = "HMAC válido · dry-run"
        } catch let error as WebhookClientError {
            switch error {
            case .unacceptableStatus(let statusCode, _) where statusCode == 401:
                statusMessage = "HMAC rechazado · verifica que coincida con el servidor"
            case .unacceptableStatus(let statusCode, _):
                statusMessage = "Prueba HMAC respondió HTTP \(statusCode)"
            case .invalidHTTPResponse:
                statusMessage = "Respuesta HTTP inválida"
            }
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    @MainActor
    private func refreshSecretStatus() async {
        do {
            secretConfigured = try await secretStore.loadRouteSecret() != nil
        } catch {
            secretConfigured = false
            statusMessage = "No se pudo leer Keychain"
        }
    }

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
    }

    private func ensureDeviceIdentity() {
        if deviceID.isEmpty {
            deviceID = "iphone-\(UUID().uuidString.lowercased())"
        }
    }
}

private struct BFFHealthResponse: Decodable {
    let status: String
    let service: String?
    let mode: String?
}

#Preview {
    IOSContentView()
}
