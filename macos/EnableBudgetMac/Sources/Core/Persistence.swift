import Foundation

struct PersistencePaths {
    static var appSupportDir: URL {
        let fm = FileManager.default
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("EnableBudget", isDirectory: true)
        if !fm.fileExists(atPath: dir.path) {
            try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        return dir
    }
    static var stateFile: URL { appSupportDir.appendingPathComponent("state.json") }
}

enum Secrets {
    static let service = "com.enablebudget.app"
    static let accAppID = "APP_ID"
    static let accPrivateKey = "PRIVATE_KEY_PEM"
    static let accSessionID = "SESSION_ID"
}

struct LocalState: Codable {
    var accounts: [[String: AnyCodable]]
    var updatedAt: Date
}

// Minimal AnyCodable for JSON roundtrip
struct AnyCodable: Codable {
    let value: Any
    init(_ value: Any) { self.value = value }
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let i = try? c.decode(Int.self) { value = i; return }
        if let d = try? c.decode(Double.self) { value = d; return }
        if let b = try? c.decode(Bool.self) { value = b; return }
        if let s = try? c.decode(String.self) { value = s; return }
        if let arr = try? c.decode([AnyCodable].self) { value = arr.map { $0.value }; return }
        if let dict = try? c.decode([String: AnyCodable].self) { value = dict.mapValues { $0.value }; return }
        value = NSNull()
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case let i as Int: try c.encode(i)
        case let d as Double: try c.encode(d)
        case let b as Bool: try c.encode(b)
        case let s as String: try c.encode(s)
        case let arr as [Any]: try c.encode(arr.map { AnyCodable($0) })
        case let dict as [String: Any]: try c.encode(dict.mapValues { AnyCodable($0) })
        default: try c.encodeNil()
        }
    }
}

enum Persistence {
    static func saveAppID(_ appID: String) throws { try Keychain.set(appID, service: Secrets.service, account: Secrets.accAppID) }
    static func loadAppID() -> String? { try? Keychain.getString(service: Secrets.service, account: Secrets.accAppID) }

    static func savePrivateKey(_ pem: String) throws { try Keychain.set(pem, service: Secrets.service, account: Secrets.accPrivateKey) }
    static func loadPrivateKey() -> String? { try? Keychain.getString(service: Secrets.service, account: Secrets.accPrivateKey) }

    static func saveSessionID(_ sid: String) throws { try Keychain.set(sid, service: Secrets.service, account: Secrets.accSessionID) }
    static func loadSessionID() -> String? { try? Keychain.getString(service: Secrets.service, account: Secrets.accSessionID) }
    static func clearSession() { Keychain.delete(service: Secrets.service, account: Secrets.accSessionID) }

    static func saveAccounts(_ accounts: [[String: Any]]) {
        let wrapped = accounts.map { $0.mapValues { AnyCodable($0) } }
        let state = LocalState(accounts: wrapped, updatedAt: Date())
        do {
            let data = try JSONEncoder().encode(state)
            try data.write(to: PersistencePaths.stateFile)
        } catch { /* best effort */ }
    }

    static func loadAccounts() -> [[String: Any]] {
        guard let data = try? Data(contentsOf: PersistencePaths.stateFile) else { return [] }
        do {
            let st = try JSONDecoder().decode(LocalState.self, from: data)
            return st.accounts.map { $0.mapValues { $0.value } }
        } catch { return [] }
    }
}

