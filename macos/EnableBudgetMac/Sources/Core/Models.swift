import Foundation

struct AccountVM: Identifiable {
    let id: String
    let name: String
    let raw: [String: Any]

    static func from(_ dict: [String: Any]) -> AccountVM? {
        guard let uid = dict["uid"] as? String ?? dict["id"] as? String else { return nil }
        let name = (dict["name"] as? String)
            ?? (dict["owner_name"] as? String)
            ?? (dict["iban"] as? String)
            ?? uid
        return AccountVM(id: uid, name: name, raw: dict)
    }
}

