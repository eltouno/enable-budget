import SwiftUI

struct ContentView: View {
    @EnvironmentObject var vm: AppViewModel
    @State private var bankName: String = ""
    @State private var country: String = "BE"

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let err = vm.lastError { Text("Erreur: \(err)").foregroundColor(.red) }

            SettingsView()

            Divider()

            if vm.sessionID == nil || vm.accounts.isEmpty {
                Text("Démarrer le consentement").font(.headline)
                HStack {
                    TextField("Nom banque (aspsp.name)", text: $bankName)
                    TextField("Pays", text: $country).frame(width: 60)
                    Button(action: { Task { await vm.startConsent(bankName: bankName, country: country) } }) {
                        if vm.isBusy { ProgressView() } else { Text("Se connecter") }
                    }.disabled(vm.appID.isEmpty || vm.privateKeyPEM.isEmpty || bankName.isEmpty)
                }
                Text("Assurez-vous que le redirect URL est whitelisté: \(vm.redirectURL)").font(.footnote).foregroundColor(.secondary)
            } else {
                NavigationStack { AccountsView() }
            }
        }
        .padding()
    }
}

struct SettingsView: View {
    @EnvironmentObject var vm: AppViewModel
    var body: some View {
        GroupBox("Réglages") {
            VStack(alignment: .leading) {
                HStack {
                    Text("APP ID:").frame(width: 100, alignment: .leading)
                    TextField("Enable APP ID", text: $vm.appID)
                }
                HStack(alignment: .top) {
                    Text("Clé privée PEM:").frame(width: 100, alignment: .leading)
                    TextEditor(text: $vm.privateKeyPEM).font(.system(.body, design: .monospaced)).frame(minHeight: 120)
                }
                HStack {
                    Text("API Base:").frame(width: 100, alignment: .leading)
                    TextField("https://api.enablebanking.com", text: $vm.apiBase)
                }
                HStack {
                    Text("Redirect URL:").frame(width: 100, alignment: .leading)
                    TextField("enablebudget://callback", text: $vm.redirectURL)
                }
                HStack {
                    Button("Enregistrer") { vm.saveCredentials() }
                    if vm.sessionID != nil { Button("Se déconnecter") { vm.signOut() } }
                }
            }
        }
    }
}
