import Foundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

public enum OutboxStatus: String, Codable, Equatable, Sendable {
    case pending
    case sending
    case sent
    case failed
}

public struct OutboxItem: Codable, Equatable, Identifiable, Sendable {
    public var id: String { payload.requestID }
    public var payload: CapturePayloadV1
    public var status: OutboxStatus
    public var attempts: Int
    public var lastError: String?
    public var createdAt: String
    public var updatedAt: String

    public init(
        payload: CapturePayloadV1,
        status: OutboxStatus = .pending,
        attempts: Int = 0,
        lastError: String? = nil,
        createdAt: String,
        updatedAt: String
    ) {
        self.payload = payload
        self.status = status
        self.attempts = attempts
        self.lastError = lastError
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    enum CodingKeys: String, CodingKey {
        case payload
        case status
        case attempts
        case lastError = "last_error"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

public actor FileOutboxStore {
    private let fileURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(fileURL: URL, encoder: JSONEncoder = .hermesCaptureEncoder(), decoder: JSONDecoder = .hermesCaptureDecoder()) {
        self.fileURL = fileURL
        self.encoder = encoder
        self.decoder = decoder
    }

    public func enqueue(_ payload: CapturePayloadV1, now: String) throws -> OutboxItem {
        try withExclusiveFileLock {
            var items = try loadAllUnlocked()
            if let existing = items.first(where: { $0.payload.requestID == payload.requestID }) {
                return existing
            }
            let item = OutboxItem(payload: payload, createdAt: now, updatedAt: now)
            items.append(item)
            try saveAllUnlocked(items)
            return item
        }
    }

    public func loadAll() throws -> [OutboxItem] {
        try withExclusiveFileLock {
            try loadAllUnlocked()
        }
    }

    private func loadAllUnlocked() throws -> [OutboxItem] {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return [] }
        let data = try Data(contentsOf: fileURL)
        if data.isEmpty { return [] }
        return try decoder.decode([OutboxItem].self, from: data)
    }

    public func loadDeliverable(maxAttempts: Int = 5, limit: Int = 10) throws -> [OutboxItem] {
        Array(
            try loadAll()
                .filter { $0.status != .sent && $0.attempts < maxAttempts }
                .prefix(limit)
        )
    }

    public func markSending(requestID: String, now: String) throws {
        try update(requestID: requestID, now: now) { item in
            item.status = .sending
            item.attempts += 1
        }
    }

    public func markSent(requestID: String, now: String) throws {
        try update(requestID: requestID, now: now) { item in
            item.status = .sent
            item.lastError = nil
        }
    }

    public func markFailed(requestID: String, message: String, now: String) throws {
        try update(requestID: requestID, now: now) { item in
            item.status = .failed
            item.lastError = message
        }
    }

    private func update(requestID: String, now: String, mutate: (inout OutboxItem) -> Void) throws {
        try withExclusiveFileLock {
            var items = try loadAllUnlocked()
            guard let index = items.firstIndex(where: { $0.payload.requestID == requestID }) else { return }
            mutate(&items[index])
            items[index].updatedAt = now
            try saveAllUnlocked(items)
        }
    }

    private func saveAllUnlocked(_ items: [OutboxItem]) throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try encoder.encode(items)
        try data.write(to: fileURL, options: [.atomic])
    }

    private func withExclusiveFileLock<T>(_ body: () throws -> T) throws -> T {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let lockURL = fileURL.appendingPathExtension("lock")
        let descriptor = lockURL.path.withCString {
            open($0, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        }
        guard descriptor >= 0 else {
            throw NSError(
                domain: "HermesCore.OutboxLock",
                code: Int(errno),
                userInfo: [NSLocalizedDescriptionKey: "Could not open outbox lock"]
            )
        }
        defer { close(descriptor) }
        guard flock(descriptor, LOCK_EX) == 0 else {
            throw NSError(
                domain: "HermesCore.OutboxLock",
                code: Int(errno),
                userInfo: [NSLocalizedDescriptionKey: "Could not lock outbox"]
            )
        }
        defer { flock(descriptor, LOCK_UN) }
        return try body()
    }
}
