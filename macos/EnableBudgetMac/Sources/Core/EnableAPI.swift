import Foundation

struct APIError: Error, LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { "HTTP \(status): \(message)" }
}

final class EnableAPI {
    var baseURL: URL
    var appID: String
    var privateKeyPEM: String
    var sessionID: String?
    var accounts: [[String: Any]] = []

    init(baseURL: URL, appID: String, privateKeyPEM: String) {
        self.baseURL = baseURL
        self.appID = appID
        self.privateKeyPEM = privateKeyPEM
    }

    private func audienceHost() -> String {
        baseURL.host ?? "api.enablebanking.com"
    }

    private func authHeader() throws -> String {
        let jwt = try JWT.makeRS256JWT(appID: appID, privateKeyPEM: privateKeyPEM, audienceHost: audienceHost())
        return "Bearer \(jwt)"
    }

    private func request(method: String, path: String, params: [String: String]? = nil, jsonBody: Any? = nil, includeSession: Bool = true) async throws -> (Int, Data) {
        var url = baseURL.appendingPathComponent(path)
        if let params = params, var comps = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            comps.queryItems = params.map { URLQueryItem(name: $0.key, value: $0.value) }
            if let u = comps.url { url = u }
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(try authHeader(), forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if includeSession, let sid = sessionID, !sid.isEmpty {
            req.setValue(sid, forHTTPHeaderField: "X-EnableBanking-Session")
        }
        if let body = jsonBody {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
        return (status, data)
    }

    func startAuth(aspspName: String, country: String, redirectURL: URL, access: [String: Any]? = nil) async throws -> (url: URL, state: String) {
        let validUntil = ISO8601DateFormatter()
        validUntil.formatOptions = [.withInternetDateTime, .withDashSeparatorInDate, .withColonSeparatorInTime]
        let v = validUntil.string(from: Date().addingTimeInterval(15 * 60))
        let state = randomState()
        var body: [String: Any] = [
            "aspsp": ["name": aspspName, "country": country],
            "redirect_url": redirectURL.absoluteString,
            "valid_until": v,
            "state": state
        ]
        if let access = access {
            body["access"] = access
        } else {
            body["access"] = [
                "valid_until": v,
                "all_accounts": ["balances", "transactions"]
            ]
        }
        let (status, data) = try await request(method: "POST", path: "/auth", jsonBody: body)
        guard status == 200 else { throw APIError(status: status, message: String(data: data, encoding: .utf8) ?? "") }
        let obj = try json(data)
        guard let urlStr = obj["url"] as? String, let url = URL(string: urlStr) else { throw APIError(status: 200, message: "Réponse /auth sans url") }
        return (url, state)
    }

    func exchangeSession(code: String) async throws {
        let (status, data) = try await request(method: "POST", path: "/sessions", jsonBody: ["code": code])
        guard status == 200 else { throw APIError(status: status, message: String(data: data, encoding: .utf8) ?? "") }
        let obj = try json(data)
        self.sessionID = obj["session_id"] as? String
        if let acc = obj["accounts"] as? [[String: Any]] { self.accounts = acc }
    }

    func balances(uid: String) async throws -> [String: Any] {
        let (status, data) = try await request(method: "GET", path: "/accounts/\(uid)/balances")
        guard status == 200 else { throw APIError(status: status, message: String(data: data, encoding: .utf8) ?? "") }
        return try json(data)
    }

    func transactions(uid: String, dateFrom: String, dateTo: String?) async throws -> [String: Any] {
        var params: [String: String] = ["date_from": dateFrom]
        if let to = dateTo { params["date_to"] = to }
        var all: [[String: Any]] = []
        var pages = 0
        var nextParams: [String: String]? = params
        while true {
            let (status, data) = try await request(method: "GET", path: "/accounts/\(uid)/transactions", params: nextParams)
            guard status == 200 else { throw APIError(status: status, message: String(data: data, encoding: .utf8) ?? "") }
            let page = try json(data)
            if let items = page["transactions"] as? [[String: Any]] {
                all.append(contentsOf: items)
            } else if let items = page["items"] as? [[String: Any]] {
                all.append(contentsOf: items)
            }
            pages += 1
            if let cont = page["continuation_key"] as? String, pages < 20 {
                nextParams = ["continuation_key": cont]
            } else {
                break
            }
        }
        return ["transactions": all, "count": all.count, "date_from": dateFrom, "date_to": dateTo ?? ""]
    }

    private func json(_ data: Data) throws -> [String: Any] {
        let obj = try JSONSerialization.jsonObject(with: data, options: [])
        guard let dict = obj as? [String: Any] else { return [:] }
        return dict
    }

    private func randomState() -> String {
        var bytes = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64EncodedString().replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "+", with: "-")
    }
}

