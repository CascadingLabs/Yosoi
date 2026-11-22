fn main() {
    println!("cargo:rustc-check-cfg=cfg(yosoi_dev_support)");
    println!("cargo:rustc-cfg=yosoi_dev_support");
}
