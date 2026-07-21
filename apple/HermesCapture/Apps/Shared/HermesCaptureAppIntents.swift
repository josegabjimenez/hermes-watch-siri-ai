import AppIntents
import Foundation
import HermesCore

enum HermesAppIntentCaptureRunner {
    static func capture(kind: QuickActionKind, text: String) async -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return "No recibí ningún texto"
        }

        let defaults = UserDefaults.standard
        let deviceID = stableDeviceID(defaults: defaults)
        let payload = CaptureFactory(
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0",
            platform: platform,
            osVersion: ProcessInfo.processInfo.operatingSystemVersionString,
            deviceID: deviceID,
            surface: surface,
            nowISO8601: {
                ISO8601DateFormatter().string(from: Date())
            },
            makeRequestID: {
                UUID().uuidString.lowercased()
            }
        ).makePayload(
            kind: kind,
            text: trimmed,
            rawText: text,
            modality: "app_intent"
        )

        let outbox = FileOutboxStore(fileURL: outboxURL)
        do {
            _ = try await outbox.enqueue(payload, now: payload.createdAt)
        } catch {
            return "No se pudo guardar la captura"
        }

        guard
            let rawBaseURL = defaults.string(forKey: "hermes.baseURL"),
            let baseURL = try? EndpointValidator.normalizedBaseURL(from: rawBaseURL),
            let secret = try? KeychainRouteSecretStore().loadRouteSecretSynchronously(),
            !secret.isEmpty
        else {
            return "Guardado. Configura Hermes desde el iPhone"
        }

        do {
            let response: CaptureResponseV1
            #if os(watchOS)
            response = try await WatchCaptureDeliveryCoordinator.deliver(
                payload: payload,
                secret: secret,
                baseURL: baseURL,
                outbox: outbox
            )
            #else
            let delivery = OutboxDeliveryService(
                store: outbox,
                client: WebhookClient(endpoint: EndpointValidator.captureURL(from: baseURL))
            )
            response = try await delivery.deliver(payload: payload, secret: secret)
            #endif
            return response.displayMessage ?? "Enviado · dry-run"
        } catch let failure as OutboxDeliveryFailure {
            return failure.localizedDescription
        } catch {
            return "Guardado para reintento"
        }
    }

    private static func stableDeviceID(defaults: UserDefaults) -> String {
        if let existing = defaults.string(forKey: "hermes.pseudonymousDeviceID"), !existing.isEmpty {
            return existing
        }
        let prefix = platform == "watchOS" ? "watch" : "iphone"
        let generated = "\(prefix)-\(UUID().uuidString.lowercased())"
        defaults.set(generated, forKey: "hermes.pseudonymousDeviceID")
        return generated
    }

    private static var outboxURL: URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return root
            .appendingPathComponent("HermesCapture", isDirectory: true)
            .appendingPathComponent("outbox.json", isDirectory: false)
    }

    private static var platform: String {
        #if os(watchOS)
        "watchOS"
        #else
        "iOS"
        #endif
    }

    private static var surface: String {
        #if os(watchOS)
        "app_intent_watch"
        #else
        "app_intent_iphone"
        #endif
    }
}

struct CaptureExpenseIntent: AppIntent {
    static var title: LocalizedStringResource = "Registrar gasto en Hermes"
    static var description = IntentDescription("Guarda y valida un gasto con Megan en modo dry-run.")
    static var openAppWhenRun = false
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresLocalDeviceAuthentication

    @Parameter(
        title: "Gasto",
        requestValueDialog: IntentDialog("¿Qué gasto quieres registrar?")
    )
    var text: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = await HermesAppIntentCaptureRunner.capture(kind: .expense, text: text)
        return .result(dialog: IntentDialog(stringLiteral: message))
    }
}

struct CaptureReminderIntent: AppIntent {
    static var title: LocalizedStringResource = "Crear recordatorio en Hermes"
    static var description = IntentDescription("Guarda y valida un recordatorio con Aura en modo dry-run.")
    static var openAppWhenRun = false
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresLocalDeviceAuthentication

    @Parameter(
        title: "Recordatorio",
        requestValueDialog: IntentDialog("¿Qué quieres recordar?")
    )
    var text: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = await HermesAppIntentCaptureRunner.capture(kind: .reminder, text: text)
        return .result(dialog: IntentDialog(stringLiteral: message))
    }
}

struct CaptureGroceryIntent: AppIntent {
    static var title: LocalizedStringResource = "Agregar al mercado en Hermes"
    static var description = IntentDescription("Guarda y valida un artículo de mercado con Aura en modo dry-run.")
    static var openAppWhenRun = false
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresLocalDeviceAuthentication

    @Parameter(
        title: "Artículo",
        requestValueDialog: IntentDialog("¿Qué quieres agregar al mercado?")
    )
    var text: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = await HermesAppIntentCaptureRunner.capture(kind: .grocery, text: text)
        return .result(dialog: IntentDialog(stringLiteral: message))
    }
}

struct GeneralHermesCaptureIntent: AppIntent {
    static var title: LocalizedStringResource = "Capturar con Hermes"
    static var description = IntentDescription("Guarda y valida una captura general con Argos en modo dry-run.")
    static var openAppWhenRun = false
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresLocalDeviceAuthentication

    @Parameter(
        title: "Captura",
        requestValueDialog: IntentDialog("¿Qué quieres capturar?")
    )
    var text: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = await HermesAppIntentCaptureRunner.capture(kind: .general, text: text)
        return .result(dialog: IntentDialog(stringLiteral: message))
    }
}

struct HermesCaptureAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: CaptureExpenseIntent(),
            phrases: [
                "Registrar gasto con \(.applicationName)",
                "Nuevo gasto en \(.applicationName)"
            ],
            shortTitle: "Registrar gasto",
            systemImageName: "creditcard"
        )
        AppShortcut(
            intent: CaptureReminderIntent(),
            phrases: [
                "Crear recordatorio con \(.applicationName)",
                "Recuérdame algo con \(.applicationName)"
            ],
            shortTitle: "Crear recordatorio",
            systemImageName: "bell"
        )
        AppShortcut(
            intent: CaptureGroceryIntent(),
            phrases: [
                "Agregar al mercado con \(.applicationName)",
                "Mercado en \(.applicationName)"
            ],
            shortTitle: "Agregar al mercado",
            systemImageName: "cart"
        )
        AppShortcut(
            intent: GeneralHermesCaptureIntent(),
            phrases: [
                "Capturar con \(.applicationName)",
                "Nueva captura en \(.applicationName)"
            ],
            shortTitle: "Capturar",
            systemImageName: "sparkles"
        )
    }

    static var shortcutTileColor: ShortcutTileColor = .red
}
