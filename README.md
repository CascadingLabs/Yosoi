<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/public/media/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/public/media/logo-light.svg">
    <img src="docs/public/media/logo-dark.svg" alt="Yosoi" width="200">
  </picture>
</p>

<h1 align="center">Yosoi</h1>
<p align="center"><strong>You Only Scrape Once (iteratively)</strong></p>
<p align="center">A performant toolkit for scraping</p>

<p align="center">
  <a href="https://discord.gg/YreV3CzxsE"><img src="https://img.shields.io/badge/Discord-Join-c4d4df?labelColor=2e3742&logo=discord&logoColor=white" alt="Join Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-c4d4df?labelColor=2e3742" alt="Apache 2.0 license"></a>
  <a href="https://doi.org/10.5281/zenodo.18713573"><img src="https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18713573-c4d4df?labelColor=2e3742" alt="DOI"></a>
  <a href="Cargo.toml"><img src="https://img.shields.io/badge/Rust-1.99%2B-c4d4df?labelColor=2e3742&logo=rust&logoColor=white" alt="Rust 1.99 or later"></a>
</p>

Yosoi unifies scraping, crawling, and browser automation into a simple toolkit for performant automation and data systems.

Use the **SDK** in your application or the **CLI** in scripts and terminal pipelines.

## Highlights

- Async HTTP and browser-backed requests
- Site URL discovery, sitemap exploration, and passive subdomain discovery
- Web search through the Rust SDK and CLI (provider preview)
- Stealth enabled by default
- Document queries with source locations attached to results
- Typed extraction contracts with explicit validation
- Local archives for inspecting and reprocessing captured documents
- Shared policies for resource limits and discovery scope
- Composable CLI commands for discovery, fetching, and extraction

## Roadmap

- Python SDK
- Automatic selector discovery from field descriptions and types
- Archive-grade browser capture and offline replay
- Search provider certification and broader coverage
- Published performance benchmarks

> [!WARNING]
> **Yosoi is currently in Beta.** The SDK and CLI is expected to change significantly. We do not expect a stable API until v1.0.0.

## Development && Contributing

See the latest in [CONTRIBUTING.MD](https://github.com/CascadingLabs/Yosoi/blob/main/CONTRIBUTING.md)


## License

[Apache License 2.0](LICENSE).

## Disclaimer

Please read [Disclaimer & Responsible Use](DISCLAIMER.md) before using Yosoi.

## Contact

For questions or concerns, email [contact@cascadinglabs.com](mailto:contact@cascadinglabs.com).

## Citation

If you use Yosoi in an academic publication, please cite it using the metadata in [CITATION.cff](CITATION.cff).
