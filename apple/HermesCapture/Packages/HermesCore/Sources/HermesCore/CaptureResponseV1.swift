import Foundation

public struct CaptureResponseV1: Codable, Equatable, Sendable {
    public var status: String
    public var dryRun: Bool?
    public var requestID: String?
    public var domain: String?
    public var displayMessage: String?
    public var question: String?
    public var duplicate: Bool?
    public var plan: CaptureResponsePlan?
    public var gatesMissing: [String]?

    public init(
        status: String,
        dryRun: Bool? = nil,
        requestID: String? = nil,
        domain: String? = nil,
        displayMessage: String? = nil,
        question: String? = nil,
        duplicate: Bool? = nil,
        plan: CaptureResponsePlan? = nil,
        gatesMissing: [String]? = nil
    ) {
        self.status = status
        self.dryRun = dryRun
        self.requestID = requestID
        self.domain = domain
        self.displayMessage = displayMessage
        self.question = question
        self.duplicate = duplicate
        self.plan = plan
        self.gatesMissing = gatesMissing
    }

    enum CodingKeys: String, CodingKey {
        case status
        case dryRun = "dry_run"
        case requestID = "request_id"
        case domain
        case displayMessage = "display_message"
        case question
        case duplicate
        case plan
        case gatesMissing = "gates_missing"
    }
}

public struct CaptureResponsePlan: Codable, Equatable, Sendable {
    public var sideEffects: [String]?
    public var wouldWrite: Bool?
    public var notes: String?

    public init(sideEffects: [String]? = nil, wouldWrite: Bool? = nil, notes: String? = nil) {
        self.sideEffects = sideEffects
        self.wouldWrite = wouldWrite
        self.notes = notes
    }

    enum CodingKeys: String, CodingKey {
        case sideEffects = "side_effects"
        case wouldWrite = "would_write"
        case notes
    }
}
