fn main() {
    // The complete facade graph is embedded, including native Surface support.
    println!("cargo:rustc-check-cfg=cfg(yosoi_dev_support)");
}
