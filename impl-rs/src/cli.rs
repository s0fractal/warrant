//! The command line: the reference's `warrant` CLI, verb for verb and flag for
//! flag, plus a few implementation-specific verbs (`edtest`, `verify-sig`).
//!
//! ```text
//! warrant-rs [--store STORE] <command> [options]
//! ```
//!
//! Abbreviated flags are refused, as the reference refuses them.

use crate::conformance::{conformance, probe, selftest};
use crate::ops::{file_warrant, resign_envelopes, respond, settle, why, Exit, Filing};
use crate::sig::{os_random_32, SigningKey};
use crate::store::Store;
use crate::verify::{verify_report_line, verify_store, Settlement};
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Flag,
    Value,
    Append,
}

struct Spec {
    opts: &'static [(&'static str, Kind)],
    required: &'static [&'static str],
    choices: &'static [(&'static str, &'static [&'static str])],
    /// Positional names; a trailing `?` is optional, a trailing `*` takes the rest.
    positionals: &'static [&'static str],
}

const FILING_OPTS: &[(&str, Kind)] = &[
    ("--subject", Kind::Value),
    ("--note", Kind::Value),
    ("--under", Kind::Append),
    ("--reason", Kind::Append),
    ("--check", Kind::Value),
    ("--runtime", Kind::Value),
    ("--verdict", Kind::Value),
    ("--transcript", Kind::Value),
    ("--evidence", Kind::Append),
    ("--prior", Kind::Append),
    ("--relitigates", Kind::Value),
    ("--actor", Kind::Value),
    ("--key", Kind::Value),
    ("--ts", Kind::Value),
];
const FILING_CHOICES: &[(&str, &[&str])] = &[
    ("--runtime", &["cmd@v1", "ski@v1"]),
    ("--verdict", &["pass", "fail"]),
];

fn spec(cmd: &str) -> Option<Spec> {
    let none: &[(&str, Kind)] = &[];
    Some(match cmd {
        "init" | "selftest" | "probe" | "edtest" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &[],
        },
        "keygen" => Spec {
            opts: &[("--out", Kind::Value)],
            required: &["--out"],
            choices: &[],
            positionals: &[],
        },
        "blob" | "policy" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["action", "file"],
        },
        "propose" => Spec {
            opts: FILING_OPTS,
            required: &["--actor", "--key"],
            choices: FILING_CHOICES,
            positionals: &[],
        },
        "accept" | "reject" | "supersede" => Spec {
            opts: FILING_OPTS,
            required: &["--actor", "--key"],
            choices: FILING_CHOICES,
            positionals: &["prior_id?"],
        },
        "why" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["id"],
        },
        "check" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["hash"],
        },
        "verify" => Spec {
            opts: &[
                ("--settlement", Kind::Flag),
                ("--genesis", Kind::Append),
                ("--trust-config", Kind::Value),
                ("--json", Kind::Flag),
                ("--store-mode", Kind::Flag),
            ],
            required: &[],
            choices: &[],
            // An optional positional store, for the store-path form older
            // callers of this binary use (`warrant-rs verify <store>`).
            positionals: &["store?"],
        },
        "settle" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["settling_wid", "candidate_body"],
        },
        "resign" => Spec {
            opts: &[("--key", Kind::Value), ("--dry-run", Kind::Flag)],
            required: &["--key"],
            choices: &[],
            positionals: &["files*"],
        },
        "conformance" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["examples?"],
        },
        "canon" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["file"],
        },
        "verify-sig" => Spec {
            opts: none,
            required: &[],
            choices: &[],
            positionals: &["key", "sig", "msg"],
        },
        _ => return None,
    })
}

#[derive(Default)]
struct Args {
    flags: BTreeMap<String, bool>,
    values: BTreeMap<String, String>,
    lists: BTreeMap<String, Vec<String>>,
    pos: BTreeMap<String, String>,
    rest: Vec<String>,
}

impl Args {
    fn flag(&self, k: &str) -> bool {
        self.flags.get(k).copied().unwrap_or(false)
    }
    fn val(&self, k: &str) -> Option<String> {
        self.values.get(k).cloned()
    }
    fn list(&self, k: &str) -> Vec<String> {
        self.lists.get(k).cloned().unwrap_or_default()
    }
    fn p(&self, k: &str) -> Option<String> {
        self.pos.get(k).cloned()
    }
}

const COMMANDS: &str = "init,keygen,blob,policy,propose,accept,reject,supersede,why,check,verify,settle,resign,conformance,selftest,probe,canon";

fn usage() -> String {
    format!("usage: warrant-rs [-h] [--store STORE] {{{COMMANDS}}} ...")
}

fn looks_negative_number(s: &str) -> bool {
    s.strip_prefix('-')
        .is_some_and(|r| !r.is_empty() && r.parse::<f64>().is_ok())
}

fn parse_sub(cmd: &str, sp: &Spec, argv: &[String]) -> Result<Args, String> {
    let mut a = Args::default();
    let mut positional: Vec<String> = Vec::new();
    let mut i = 0;
    let mut only_pos = false;
    while i < argv.len() {
        let tok = &argv[i];
        i += 1;
        if only_pos || !tok.starts_with('-') || tok == "-" || looks_negative_number(tok) {
            positional.push(tok.clone());
            continue;
        }
        if tok == "--" {
            only_pos = true;
            continue;
        }
        let (name, inline) = match tok.split_once('=') {
            Some((n, v)) if n.starts_with("--") => (n.to_string(), Some(v.to_string())),
            _ => (tok.clone(), None),
        };
        let Some(&(_, kind)) = sp.opts.iter().find(|(n, _)| *n == name) else {
            return Err(format!("unrecognized arguments: {tok}"));
        };
        if kind == Kind::Flag {
            if inline.is_some() {
                return Err(format!(
                    "argument {name}: ignored explicit argument {:?}",
                    inline.unwrap()
                ));
            }
            a.flags.insert(name, true);
            continue;
        }
        let value = match inline {
            Some(v) => v,
            None => {
                let v = argv.get(i).filter(|v| {
                    !v.starts_with('-') || looks_negative_number(v) || v.as_str() == "-"
                });
                let v = v.ok_or_else(|| format!("argument {name}: expected one argument"))?;
                i += 1;
                v.clone()
            }
        };
        if let Some((_, ch)) = sp.choices.iter().find(|(n, _)| *n == name) {
            if !ch.contains(&value.as_str()) {
                let opts: Vec<String> = ch.iter().map(|c| format!("'{c}'")).collect();
                return Err(format!(
                    "argument {name}: invalid choice: '{value}' (choose from {})",
                    opts.join(", ")
                ));
            }
        }
        match kind {
            Kind::Append => a.lists.entry(name).or_default().push(value),
            _ => {
                a.values.insert(name, value);
            }
        }
    }
    let missing: Vec<&str> = sp
        .required
        .iter()
        .copied()
        .filter(|r| !a.values.contains_key(*r))
        .collect();
    let mut pi = positional.into_iter();
    let mut missing_pos = Vec::new();
    for name in sp.positionals {
        if let Some(n) = name.strip_suffix('*') {
            a.rest = pi.by_ref().collect();
            let _ = n;
        } else if let Some(n) = name.strip_suffix('?') {
            if let Some(v) = pi.next() {
                a.pos.insert(n.to_string(), v);
            }
        } else {
            match pi.next() {
                Some(v) => {
                    a.pos.insert(name.to_string(), v);
                }
                None => missing_pos.push(*name),
            }
        }
    }
    let extra: Vec<String> = pi.collect();
    if !missing.is_empty() || !missing_pos.is_empty() {
        let all: Vec<&str> = missing_pos.into_iter().chain(missing).collect();
        return Err(format!(
            "the following arguments are required: {}",
            all.join(", ")
        ));
    }
    if !extra.is_empty() {
        return Err(format!("unrecognized arguments: {}", extra.join(" ")));
    }
    if (cmd == "blob" || cmd == "policy") && a.p("action").as_deref() != Some("add") {
        return Err(format!(
            "argument action: invalid choice: '{}' (choose from 'add')",
            a.p("action").unwrap_or_default()
        ));
    }
    Ok(a)
}

/// Python `int()` for `--ts`.
fn parse_int(s: &str) -> Option<i128> {
    let t = s.trim();
    let (neg, d) = match t.as_bytes().first() {
        Some(b'-') => (true, &t[1..]),
        Some(b'+') => (false, &t[1..]),
        _ => (false, t),
    };
    if d.is_empty() || d.starts_with('_') || d.ends_with('_') || d.contains("__") {
        return None;
    }
    let clean: String = d.chars().filter(|c| *c != '_').collect();
    if !clean.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let n = clean.parse::<i128>().ok()?;
    Some(if neg { -n } else { n })
}

/// Python's `str(Path(p))`: repeated and trailing slashes and `.` segments dropped.
pub fn py_path(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let abs = p.starts_with('/');
    let lead2 = p.starts_with("//") && !p.starts_with("///");
    let parts: Vec<&str> = p
        .split('/')
        .filter(|s| !s.is_empty() && *s != ".")
        .collect();
    let joined = parts.join("/");
    match (abs, joined.is_empty()) {
        (true, _) if lead2 => format!("//{joined}"),
        (true, _) => format!("/{joined}"),
        (false, true) => ".".into(),
        (false, false) => joined,
    }
}

fn filing(a: &Args) -> Result<Filing, String> {
    let ts = match a.val("--ts") {
        None => None,
        Some(t) => {
            Some(parse_int(&t).ok_or_else(|| format!("argument --ts: invalid int value: '{t}'"))?)
        }
    };
    Ok(Filing {
        subject: a.val("--subject"),
        note: a.val("--note"),
        under: a.list("--under"),
        reason: a.list("--reason"),
        check: a.val("--check"),
        runtime: a.val("--runtime").unwrap_or_else(|| "cmd@v1".into()),
        verdict: a.val("--verdict").unwrap_or_else(|| "pass".into()),
        transcript: a.val("--transcript"),
        evidence: a.list("--evidence"),
        prior: a.list("--prior"),
        relitigates: a.val("--relitigates"),
        actor: a.val("--actor").unwrap_or_default(),
        key: a.val("--key").unwrap_or_default(),
        ts,
        under_json: Vec::new(),
    })
}

fn require(store: &Store) -> Result<(), Exit> {
    if store.is_initialized() {
        Ok(())
    } else {
        Err(Exit::msg(format!(
            "no store at {} (run: warrant init)",
            py_path(&store.root.display().to_string())
        )))
    }
}

const NO_SETTLEMENT_FLAGS: &str = "--trust-config/--genesis are used only by settlement-grade verification, and were supplied without --settlement.\n  run:  warrant verify --settlement --trust-config <file>\nWithout --settlement the key<->actor binding is not derived at all, and every signature is reported as unverified binding -- which would have been misleading here, since you did provide a keyring.";

/// Run the CLI over `argv` (without the program name). Returns the exit status.
pub fn run(argv: &[String]) -> u8 {
    match dispatch(argv) {
        Ok(()) => 0,
        Err(Exit { code, message }) => {
            if let Some(m) = message {
                eprintln!("{m}");
            }
            code
        }
    }
}

fn usage_error(cmd: Option<&str>, msg: &str) -> Exit {
    let prog = match cmd {
        Some(c) => format!("warrant-rs {c}"),
        None => "warrant-rs".into(),
    };
    eprintln!("{}\n{prog}: error: {msg}", usage());
    Exit::code(2)
}

fn dispatch(argv: &[String]) -> Result<(), Exit> {
    let mut store_root = ".warrants".to_string();
    let mut i = 0;
    while i < argv.len() && argv[i].starts_with('-') {
        let tok = &argv[i];
        if tok == "-h" || tok == "--help" {
            println!(
                "{}\n\nWarrant — an independent Rust implementation of the reference CLI.",
                usage()
            );
            return Ok(());
        }
        if tok == "--store" {
            store_root = argv
                .get(i + 1)
                .cloned()
                .ok_or_else(|| usage_error(None, "argument --store: expected one argument"))?;
            i += 2;
        } else if let Some(v) = tok.strip_prefix("--store=") {
            store_root = v.to_string();
            i += 1;
        } else {
            return Err(usage_error(None, &format!("unrecognized arguments: {tok}")));
        }
    }
    let Some(cmd) = argv.get(i).map(String::as_str) else {
        return Err(usage_error(
            None,
            "the following arguments are required: cmd",
        ));
    };
    let Some(sp) = spec(cmd) else {
        return Err(usage_error(
            None,
            &format!("argument cmd: invalid choice: '{cmd}'"),
        ));
    };
    let rest = &argv[i + 1..];
    if rest.iter().any(|t| t == "-h" || t == "--help") {
        println!("usage: warrant-rs {cmd} (see the reference CLI: `warrant {cmd} --help`)");
        return Ok(());
    }
    let a = parse_sub(cmd, &sp, rest).map_err(|m| usage_error(Some(cmd), &m))?;
    // Pure argv invariants, checked before any store access.
    if cmd == "propose" && a.val("--subject").filter(|s| !s.is_empty()).is_none() {
        return Err(usage_error(Some(cmd), "propose requires --subject"));
    }
    if matches!(cmd, "accept" | "reject" | "supersede") && a.p("prior_id").is_none() {
        if cmd == "supersede" {
            return Err(usage_error(
                Some(cmd),
                "supersede requires the warrant id being superseded",
            ));
        }
        if a.val("--subject").filter(|s| !s.is_empty()).is_none() || a.list("--under").is_empty() {
            return Err(usage_error(
                Some(cmd),
                &format!("{cmd} without a prior requires --subject and --under"),
            ));
        }
    }
    let store = Store::new(&store_root);
    match cmd {
        "init" => {
            store.init().map_err(|e| Exit::msg(e.to_string()))?;
            println!("initialized {}", py_path(&store_root));
        }
        "keygen" => {
            let out = a.val("--out").unwrap();
            let seed = os_random_32().map_err(Exit::msg)?;
            std::fs::write(&out, crate::hash::encode_hex(&seed) + "\n")
                .map_err(|e| Exit::msg(e.to_string()))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&out, std::fs::Permissions::from_mode(0o600))
                    .map_err(|e| Exit::msg(e.to_string()))?;
            }
            println!("pubkey {}", SigningKey::from_seed(seed).public_hex());
        }
        "blob" | "policy" => {
            require(&store)?;
            let f = a.p("file").unwrap();
            let data = std::fs::read(&f).map_err(|e| Exit::msg(format!("cannot read {f}: {e}")))?;
            println!(
                "{}",
                store
                    .put_blob(&data)
                    .map_err(|e| Exit::msg(e.to_string()))?
            );
        }
        "propose" => {
            require(&store)?;
            let f = filing(&a).map_err(|m| usage_error(Some(cmd), &m))?;
            let subject = crate::ops::resolve_blob_arg(&store, f.subject.as_deref().unwrap_or(""))?;
            let note = f
                .note
                .clone()
                .filter(|n| !n.is_empty())
                .map(crate::json::Json::Str);
            file_warrant(&store, "propose", crate::json::Json::Str(subject), &f, note)?;
        }
        "accept" | "reject" | "supersede" => {
            require(&store)?;
            let f = filing(&a).map_err(|m| usage_error(Some(cmd), &m))?;
            respond(&store, cmd, a.p("prior_id").as_deref(), &f)?;
        }
        "why" => {
            require(&store)?;
            let (missing, failed) = why(&store, &a.p("id").unwrap())?;
            if missing > 0 || failed > 0 {
                return Err(Exit::code(1));
            }
        }
        "check" => {
            require(&store)?;
            match crate::ski::run_ski_check(&store.blobs, &a.p("hash").unwrap()) {
                Err(e) => return Err(Exit::msg(format!("ski@v1 unverified: {e}"))),
                Ok((verdict, rh, spent)) => {
                    println!("{verdict}  result={rh}  atp_spent={spent}");
                    if verdict != "pass" {
                        return Err(Exit::code(1));
                    }
                }
            }
        }
        "verify" => {
            let store = match a.p("store") {
                Some(s) => Store::new(s),
                None => store,
            };
            let genesis = a.list("--genesis");
            let trust = a.val("--trust-config");
            if !a.flag("--settlement")
                && (trust.as_deref().is_some_and(|t| !t.is_empty()) || !genesis.is_empty())
            {
                return Err(Exit::msg(NO_SETTLEMENT_FLAGS));
            }
            let settlement = a.flag("--settlement").then_some(Settlement {
                genesis_roots: genesis,
                trust_config: trust,
            });
            if a.flag("--json") {
                let (line, ok) = verify_report_line(&store, settlement.as_ref());
                println!("{line}");
                return if ok { Ok(()) } else { Err(Exit::code(1)) };
            }
            require(&store)?;
            let r = verify_store(&store, false, settlement.as_ref());
            print!("{}", r.text);
            if r.errors > 0 {
                return Err(Exit::code(1));
            }
        }
        "settle" => {
            require(&store)?;
            if !settle(
                &store,
                &a.p("settling_wid").unwrap(),
                &a.p("candidate_body").unwrap(),
            )? {
                return Err(Exit::code(1));
            }
        }
        "resign" => {
            let paths: Vec<PathBuf> = if !a.rest.is_empty() {
                a.rest.iter().map(|f| PathBuf::from(py_path(f))).collect()
            } else if store.is_initialized() {
                store
                    .record_files()
                    .iter()
                    .map(|n| PathBuf::from(py_path(&format!("{store_root}/records/{n}"))))
                    .collect()
            } else {
                Vec::new()
            };
            if paths.is_empty() {
                return Err(Exit::msg(format!(
                    "nothing to re-sign: no envelope files given and {} holds no records",
                    py_path(&format!("{store_root}/records"))
                )));
            }
            let key = SigningKey::load(&a.val("--key").unwrap()).map_err(Exit::msg)?;
            let dry = a.flag("--dry-run");
            let r = resign_envelopes(&paths, &key, dry);
            println!(
                "\nresign: {} envelopes, {} signatures {}, {} already warrant-sig-v1, {} NOT migratable",
                r.files,
                r.resigned,
                if dry { "to re-sign" } else { "re-signed" },
                r.already_current,
                r.unmigratable.len()
            );
            for (path, wid, reason) in &r.unmigratable {
                println!(
                    "  NOT MIGRATED  {}  {path}\n                {reason}",
                    crate::json::prefix(wid.as_deref().unwrap_or("?"), 12)
                );
            }
            for (path, before, after) in &r.id_moved {
                println!(
                    "  REFUSED (WarrantID moved {} -> {}) {path}",
                    crate::json::prefix(before, 12),
                    crate::json::prefix(after, 12)
                );
            }
            if !r.unmigratable.is_empty() || !r.id_moved.is_empty() {
                return Err(Exit::code(1));
            }
        }
        "conformance" => {
            let dir = a.p("examples").unwrap_or_else(|| "examples".into());
            if !conformance(&dir).map_err(Exit::msg)? {
                return Err(Exit::code(1));
            }
        }
        "selftest" => {
            selftest().map_err(Exit::msg)?;
        }
        "probe" => probe().map_err(Exit::msg)?,
        "canon" => {
            let f = a.p("file").unwrap();
            let text = std::fs::read_to_string(&f)
                .map_err(|e| Exit::msg(format!("cannot read {f}: {e}")))?;
            let body =
                crate::json::parse_ijson_str(&text).map_err(|e| Exit::msg(format!("{f}: {e}")))?;
            let raw = crate::json::canon(&body).map_err(|e| Exit::msg(e.to_string()))?;
            println!(
                "{{\"warrant_id\": \"{}\", \"canon_hex\": \"{}\"}}",
                crate::hash::blob_hash(&raw),
                crate::hash::encode_hex(&raw)
            );
        }
        "edtest" => {
            if crate::ed25519::selftest() {
                println!("ED25519 SELFTEST: ALL PASS");
            } else {
                println!("ED25519 SELFTEST: FAILURES");
                return Err(Exit::code(1));
            }
        }
        "verify-sig" => {
            // verify-sig <pubkey_hex> <sig_hex> <msg_hex> -> true|false (raw
            // Ed25519 over arbitrary bytes, weak keys refused; for differentials).
            let h = |k: &str| crate::hash::fromhex(&a.p(k).unwrap());
            let ok = match (h("key"), h("sig"), h("msg")) {
                (Some(k), Some(s), Some(m))
                    if k.len() == 32 && s.len() == 64 && !crate::sig::weak_ed25519_pubkey(&k) =>
                {
                    crate::ed25519::verify(&k.try_into().unwrap(), &s.try_into().unwrap(), &m)
                }
                _ => false,
            };
            println!("{ok}");
        }
        _ => unreachable!(),
    }
    Ok(())
}
