//! `warrant-rs`: the Warrant CLI, as an independent Rust implementation.
//! See the library documentation (`warrant_verify`) and `warrant-rs --help`.

fn main() -> std::process::ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    std::process::ExitCode::from(warrant_verify::cli::run(&argv))
}
