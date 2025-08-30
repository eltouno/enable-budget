import Foundation
import Security

enum JWTError: Error { case invalidKey, signFailed, pemParse }

struct JWT {
    static func base64urlEncode(_ data: Data) -> String {
        var s = data.base64EncodedString()
        s = s.replacingOccurrences(of: "+", with: "-")
             .replacingOccurrences(of: "/", with: "_")
             .replacingOccurrences(of: "=", with: "")
        return s
    }

    static func base64urlEncodeJSON(_ obj: Any) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: obj, options: [])
        return base64urlEncode(data)
    }

    static func importRSAPrivateKey(pem: String) throws -> SecKey {
        guard let raw = PEMUtils.stripPEMHeaders(pem) else { throw JWTError.pemParse }
        let der: Data
        if PEMUtils.isPKCS8(pem) {
            der = raw
        } else if PEMUtils.isPKCS1(pem) {
            der = PEMUtils.wrapRSAPKCS1ToPKCS8(raw)
        } else {
            // Tente brut (PKCS#8)
            der = raw
        }
        let attrs: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeRSA,
            kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
            kSecAttrKeySizeInBits as String: 2048
        ]
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateWithData(der as CFData, attrs as CFDictionary, &error) else {
            // Essai 4096 bits au cas où
            let attrs2: [String: Any] = [
                kSecAttrKeyType as String: kSecAttrKeyTypeRSA,
                kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
                kSecAttrKeySizeInBits as String: 4096
            ]
            var error2: Unmanaged<CFError>?
            guard let key2 = SecKeyCreateWithData(der as CFData, attrs2 as CFDictionary, &error2) else {
                throw error2?.takeRetainedValue() ?? JWTError.invalidKey
            }
            return key2
        }
        return key
    }

    static func signRS256(message: Data, with privateKey: SecKey) throws -> Data {
        let algo = SecKeyAlgorithm.rsaSignatureMessagePKCS1v15SHA256
        guard SecKeyIsAlgorithmSupported(privateKey, .sign, algo) else { throw JWTError.invalidKey }
        var error: Unmanaged<CFError>?
        guard let sig = SecKeyCreateSignature(privateKey, algo, message as CFData, &error) as Data? else {
            throw error?.takeRetainedValue() ?? JWTError.signFailed
        }
        return sig
    }

    static func makeRS256JWT(appID: String, privateKeyPEM: String, audienceHost: String) throws -> String {
        let header: [String: Any] = [
            "alg": "RS256",
            "kid": appID,
            "typ": "JWT"
        ]
        let now = Int(Date().timeIntervalSince1970)
        let payload: [String: Any] = [
            "iss": "enablebanking.com",
            "aud": audienceHost,
            "iat": now,
            "exp": now + 300
        ]
        let header64 = try base64urlEncodeJSON(header)
        let payload64 = try base64urlEncodeJSON(payload)
        let signingInput = (header64 + "." + payload64).data(using: .utf8)!
        let key = try importRSAPrivateKey(pem: privateKeyPEM)
        let sig = try signRS256(message: signingInput, with: key)
        let sig64 = base64urlEncode(sig)
        return header64 + "." + payload64 + "." + sig64
    }
}

