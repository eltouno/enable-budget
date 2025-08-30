import Foundation

struct CSVExporter {
    static func flatten(_ obj: Any, prefix: String = "") -> [String: Any] {
        var out: [String: Any] = [:]
        if let dict = obj as? [String: Any] {
            for (k, v) in dict {
                let key = prefix.isEmpty ? k : "\(prefix).\(k)"
                if v is [String: Any] {
                    out.merge(flatten(v, prefix: key)) { $1 }
                } else if let arr = v as? [Any] {
                    if let data = try? JSONSerialization.data(withJSONObject: arr, options: []) {
                        out[key] = String(data: data, encoding: .utf8) ?? ""
                    } else { out[key] = "" }
                } else {
                    out[key] = v
                }
            }
        } else {
            out[prefix.isEmpty ? "value" : prefix] = obj
        }
        return out
    }

    static func toCSV(transactions: [Any]) -> String {
        let rows = transactions.map { flatten($0) }
        let headers = Array(Set(rows.flatMap { $0.keys })).sorted()
        var lines: [String] = []
        lines.append(headers.joined(separator: ","))
        for r in rows {
            let vals: [String] = headers.map { key in
                if let v = r[key] {
                    return escapeCSV(String(describing: v))
                } else { return "" }
            }
            lines.append(vals.joined(separator: ","))
        }
        return lines.joined(separator: "\n")
    }

    private static func escapeCSV(_ s: String) -> String {
        if s.contains(",") || s.contains("\n") || s.contains("\"") {
            let q = s.replacingOccurrences(of: "\"", with: "\"\"")
            return "\"\(q)\""
        }
        return s
    }
}

