import Foundation

public enum EndpointValidationError: Error, Equatable, LocalizedError, Sendable {
    case empty
    case invalidURL
    case httpsRequired
    case hostRequired

    public var errorDescription: String? {
        switch self {
        case .empty:
            return "Ingresa el endpoint del BFF"
        case .invalidURL:
            return "El endpoint no es una URL válida"
        case .httpsRequired:
            return "El endpoint debe usar HTTPS"
        case .hostRequired:
            return "El endpoint debe incluir un host"
        }
    }
}

public enum EndpointValidator {
    public static func normalizedBaseURL(from rawValue: String) throws -> URL {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw EndpointValidationError.empty
        }
        guard var components = URLComponents(string: trimmed) else {
            throw EndpointValidationError.invalidURL
        }
        guard components.scheme?.lowercased() == "https" else {
            throw EndpointValidationError.httpsRequired
        }
        guard let host = components.host, !host.isEmpty else {
            throw EndpointValidationError.hostRequired
        }

        components.scheme = "https"
        components.path = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if !components.path.isEmpty {
            components.path = "/\(components.path)"
        }
        components.query = nil
        components.fragment = nil

        guard let url = components.url else {
            throw EndpointValidationError.invalidURL
        }
        return url
    }

    public static func healthURL(from baseURL: URL) -> URL {
        baseURL.appendingPathComponent("health")
    }
}
