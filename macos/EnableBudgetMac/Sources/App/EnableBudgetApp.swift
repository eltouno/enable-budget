import SwiftUI

@MainActor
final class AppViewModel: ObservableObject {
    @Published var appID: String = Persistence.loadAppID() ?? ""
    @Published var privateKeyPEM: String = Persistence.loadPrivateKey() ?? ""
    @Published var apiBase: String = "https://api.enablebanking.com"
    @Published var redirectURL: String = "enablebudget://callback"
    @Published var sessionID: String? = Persistence.loadSessionID()
    @Published var accounts: [AccountVM] = Persistence.loadAccounts().compactMap(AccountVM.from)
    @Published var isBusy: Bool = false
    @Published var lastError: String?

    private var api: EnableAPI? {
        guard let url = URL(string: apiBase), !appID.isEmpty, !privateKeyPEM.isEmpty else { return nil }
        let client = EnableAPI(baseURL: url, appID: appID, privateKeyPEM: privateKeyPEM)
        client.sessionID = sessionID
        client.accounts = accounts.map { $0.raw }
        return client
    }

    func apiClient() -> EnableAPI? { api }

    func saveCredentials() {
        do {
            try Persistence.saveAppID(appID)
            try Persistence.savePrivateKey(privateKeyPEM)
        } catch { lastError = String(describing: error) }
    }

    func startConsent(bankName: String, country: String) async {
        guard let api = self.api, let redirect = URL(string: redirectURL) else { return }
        isBusy = true; defer { isBusy = false }
        do {
            let (authURL, state) = try await api.startAuth(aspspName: bankName, country: country, redirectURL: redirect)
            let web = WebAuthSession()
            let (code, retState) = try await web.start(authURL: authURL, callbackScheme: redirect.scheme ?? "enablebudget")
            if let rs = retState, state != rs {
                lastError = "State invalide au retour"; return
            }
            try await api.exchangeSession(code: code)
            self.sessionID = api.sessionID
            if let sid = api.sessionID { try Persistence.saveSessionID(sid) }
            let acc = api.accounts
            Persistence.saveAccounts(acc)
            self.accounts = acc.compactMap(AccountVM.from)
        } catch {
            lastError = String(describing: error)
        }
    }

    func signOut() {
        sessionID = nil
        Persistence.clearSession()
    }
}

@main
struct EnableBudgetApp: App {
    @StateObject var appVM = AppViewModel()
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appVM)
        }
    }
}
