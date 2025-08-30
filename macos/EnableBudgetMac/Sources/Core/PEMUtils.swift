import Foundation

enum PEMError: Error { case invalidPEM, invalidBase64 }

struct PEMUtils {
    static func stripPEMHeaders(_ pem: String) -> Data? {
        let lines = pem
            .replacingOccurrences(of: "\r", with: "")
            .components(separatedBy: "\n")
            .filter { !$0.hasPrefix("---") && !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        let base64 = lines.joined()
        return Data(base64Encoded: base64)
    }

    static func isPKCS8(_ pem: String) -> Bool { pem.contains("BEGIN PRIVATE KEY") }
    static func isPKCS1(_ pem: String) -> Bool { pem.contains("BEGIN RSA PRIVATE KEY") }

    // Wrap PKCS#1 RSAPrivateKey DER into PKCS#8 PrivateKeyInfo DER
    // PrivateKeyInfo ::= SEQUENCE {
    //   version                   Version,
    //   privateKeyAlgorithm       AlgorithmIdentifier,
    //   privateKey                OCTET STRING
    // }
    // AlgorithmIdentifier for rsaEncryption: 1.2.840.113549.1.1.1 with NULL
    static func wrapRSAPKCS1ToPKCS8(_ pkcs1DER: Data) -> Data {
        // Build AlgorithmIdentifier for rsaEncryption
        let oidRSA: [UInt8] = [0x06, 0x09, 0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x01, 0x01]
        let algId = asn1Sequence(Data(oidRSA) + Data([0x05, 0x00])) // NULL
        // version = INTEGER 0
        let version: [UInt8] = [0x02, 0x01, 0x00]
        // privateKey OCTET STRING (pkcs1 der)
        let pkcs1Octet = asn1OctetString(pkcs1DER)
        let body = Data(version) + algId + pkcs1Octet
        return asn1Sequence(body)
    }

    // Minimal ASN.1 helpers
    static func asn1Length(_ length: Int) -> Data {
        if length < 0x80 { return Data([UInt8(length)]) }
        var len = length
        var bytes: [UInt8] = []
        while len > 0 { bytes.insert(UInt8(len & 0xFF), at: 0); len >>= 8 }
        return Data([0x80 | UInt8(bytes.count)] + bytes)
    }
    static func asn1Sequence(_ body: Data) -> Data { Data([0x30]) + asn1Length(body.count) + body }
    static func asn1OctetString(_ body: Data) -> Data { Data([0x04]) + asn1Length(body.count) + body }
}

