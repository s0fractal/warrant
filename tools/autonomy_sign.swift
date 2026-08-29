#!/usr/bin/env swift
// Maintainer-only signer for the autonomy standing authorization.
//
// The P-256 private key is generated inside this Mac's Secure Enclave. Its
// dataRepresentation is an opaque, device-bound handle stored outside the
// repository; the signing operation requires user presence (Touch ID or the
// device passcode). Only the public key and detached authorization are written
// into the repository.

import CryptoKit
import Darwin
import Foundation
import LocalAuthentication
import Security

enum SignerFailure: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self { case .message(let text): return text }
    }
}

let repository = "s0fractal/warrant"
let baseBranch = "master"
let policyPath = "policies/agent-autonomy-v0.1.json"
let publicPath = "trust/maintainer-autonomy-p256.pub"
let authorizationPath = "trust/agent-autonomy-authorization.json"
let authorizationFormat = "agent-autonomy-authorization@v0.1"
let authorizedActions = [
    "branch_push", "draft_pull_request", "pull_request_update",
    "ready_for_review", "merge",
]

func fail(_ text: String) throws -> Never { throw SignerFailure.message(text) }

func repositoryRoot() throws -> URL {
    let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath,
                   isDirectory: true).standardizedFileURL
    guard FileManager.default.fileExists(atPath: root.appendingPathComponent(".git").path),
          FileManager.default.fileExists(atPath: root.appendingPathComponent(policyPath).path)
    else { try fail("run this command from the warrant repository root") }
    return root
}

func keyHandleURL() throws -> URL {
    let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                        in: .userDomainMask).first
    guard let base else { try fail("cannot locate Application Support") }
    return base.appendingPathComponent("Warrant", isDirectory: true)
        .appendingPathComponent("autonomy-p256-secure-enclave.key")
}

func writePrivateFile(_ data: Data, to url: URL) throws {
    try FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700])
    try data.write(to: url, options: .atomic)
    try FileManager.default.setAttributes([.posixPermissions: 0o600],
                                          ofItemAtPath: url.path)
}

func loadOrCreateKey() throws -> SecureEnclave.P256.Signing.PrivateKey {
    guard SecureEnclave.isAvailable else {
        try fail("Secure Enclave is unavailable; do not fall back silently")
    }
    let keyURL = try keyHandleURL()
    let context = LAContext()
    context.localizedReason = "Authorize Warrant's bounded agent autonomy policy"
    if FileManager.default.fileExists(atPath: keyURL.path) {
        let representation = try Data(contentsOf: keyURL)
        print("Using existing Secure Enclave key handle at \(keyURL.path)")
        return try SecureEnclave.P256.Signing.PrivateKey(
            dataRepresentation: representation,
            authenticationContext: context)
    }

    var accessError: Unmanaged<CFError>?
    guard let access = SecAccessControlCreateWithFlags(
        nil,
        kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        [.privateKeyUsage, .userPresence],
        &accessError)
    else {
        let detail = accessError?.takeRetainedValue().localizedDescription
            ?? "unknown access-control error"
        try fail("cannot create user-presence access control: \(detail)")
    }
    let key = try SecureEnclave.P256.Signing.PrivateKey(
        accessControl: access,
        authenticationContext: context)
    try writePrivateFile(key.dataRepresentation, to: keyURL)
    print("Created a non-exportable Secure Enclave key; stored its device-bound handle at \(keyURL.path)")
    return key
}

func iso8601(_ date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime]
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    return formatter.string(from: date)
}

func canonical(_ object: [String: Any]) throws -> Data {
    guard JSONSerialization.isValidJSONObject(object) else {
        try fail("authorization is not valid JSON")
    }
    return try JSONSerialization.data(
        withJSONObject: object,
        options: [.sortedKeys, .withoutEscapingSlashes])
}

func authorize(days: Int) throws {
    guard (1...365).contains(days) else {
        try fail("--days must be between 1 and 365")
    }
    let root = try repositoryRoot()
    let policyURL = root.appendingPathComponent(policyPath)
    let policy = try Data(contentsOf: policyURL)
    let policyHash = SHA256.hash(data: policy).map { String(format: "%02x", $0) }.joined()

    let now = Date()
    let signed: [String: Any] = [
        "actions": authorizedActions,
        "authorization_format": authorizationFormat,
        "base_branch": baseBranch,
        "not_after": iso8601(now.addingTimeInterval(TimeInterval(days * 86_400))),
        "not_before": iso8601(now.addingTimeInterval(-300)),
        "policy_sha256": policyHash,
        "repository": repository,
    ]

    print("Policy SHA-256: \(policyHash)")
    print("Actions: \(authorizedActions.joined(separator: ", "))")
    print("Validity: \(signed["not_before"]!) through \(signed["not_after"]!)")
    print("macOS will now require your presence to sign these exact bytes.")

    let key = try loadOrCreateKey()
    let message = try canonical(signed)
    let signature = try key.signature(for: message)

    let publicText = "p256-x963:" + key.publicKey.x963Representation.base64EncodedString() + "\n"
    var authorization = signed
    authorization["signature"] = signature.derRepresentation.base64EncodedString()
    let authData = try JSONSerialization.data(
        withJSONObject: authorization,
        options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) + Data("\n".utf8)

    let trustDirectory = root.appendingPathComponent("trust", isDirectory: true)
    try FileManager.default.createDirectory(at: trustDirectory,
                                            withIntermediateDirectories: true)
    try Data(publicText.utf8).write(to: root.appendingPathComponent(publicPath),
                                    options: .atomic)
    try authData.write(to: root.appendingPathComponent(authorizationPath),
                       options: .atomic)
    print("Wrote only public material:")
    print("  \(publicPath)")
    print("  \(authorizationPath)")
}

do {
    let args = Array(CommandLine.arguments.dropFirst())
    guard args.first == "authorize" else {
        try fail("usage: swift tools/autonomy_sign.swift authorize [--days 365]")
    }
    var days = 365
    if args.count == 3 && args[1] == "--days", let parsed = Int(args[2]) {
        days = parsed
    } else if args.count != 1 {
        try fail("usage: swift tools/autonomy_sign.swift authorize [--days 365]")
    }
    try authorize(days: days)
} catch {
    fputs("autonomy signer refused: \(error)\n", stderr)
    exit(2)
}
