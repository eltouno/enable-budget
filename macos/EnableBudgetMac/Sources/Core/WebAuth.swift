import Foundation
import AuthenticationServices

final class WebAuthSession: NSObject {
    private var session: ASWebAuthenticationSession?

    func start(authURL: URL, callbackScheme: String) async throws -> (code: String, state: String?) {
        return try await withCheckedThrowingContinuation { cont in
            self.session = ASWebAuthenticationSession(url: authURL, callbackURLScheme: callbackScheme) { url, error in
                self.session = nil
                if let error = error { cont.resume(throwing: error); return }
                guard let url = url, let comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
                    cont.resume(throwing: URLError(.badURL)); return
                }
                let code = comps.queryItems?.first(where: { $0.name == "code" })?.value
                let state = comps.queryItems?.first(where: { $0.name == "state" })?.value
                if let code = code { cont.resume(returning: (code, state)) }
                else { cont.resume(throwing: URLError(.badServerResponse)) }
            }
            if #available(macOS 13.0, *) {
                self.session?.prefersEphemeralWebBrowserSession = false
            }
            self.session?.presentationContextProvider = self
            _ = self.session?.start()
        }
    }
}

extension WebAuthSession: ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        return ASPresentationAnchor()
    }
}

