<p align="center">
  <a href="https://cascadinglabs.com/yosoi">
    <img src="media/yosoiIcon.svg" alt="Yosoi" width="200">
  </a>
</p>

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18713573.svg)](https://doi.org/10.5281/zenodo.18713573)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Actions status](https://github.com/CascadingLabs/Yosoi/actions/workflows/CI.yaml/badge.svg)](https://github.com/CascadingLabs/Yosoi/actions)
[![image](https://img.shields.io/pypi/pyversions/yosoi.svg)](https://pypi.python.org/pypi/yosoi)
[![image](https://img.shields.io/pypi/v/yosoi.svg)](https://pypi.python.org/pypi/yosoi)
[![codecov](https://codecov.io/gh/CascadingLabs/Yosoi/graph/badge.svg?token=DFDI574EEA)](https://codecov.io/gh/CascadingLabs/Yosoi)
[![docs](https://img.shields.io/badge/docs-cascadinglabs.com%2Fyosoi-blue)](https://cascadinglabs.com/yosoi)
 <!--[![image](https://img.shields.io/pypi/l/yosoi.svg)](https://pypi.python.org/pypi/yosoi) -->



> [!WARNING]
> **Yosoi is currently in Alpha.** The API is expected to change significantly. We do not expect a stable API until we are out of Beta.

# Yosoi - You Only Scrape Once (iteratively)

> **Discover once, scrape forever**

Give Yosoi a URL, domain, or group of URLs, and it uses AI to automatically discover the best selectors for structured content.

## Installation

```bash
# Install yosoi using uv
uv add yosoi
```

## Quick Start

### API Key
Export your API Key or create a `.env` file
```bash
# Set keys for whichever providers you want to use
<PROVIDER_NAME>_KEY=your_api_key_here      
GROQ_API_KEY=your_groq_key_here               # groq/...
GEMINI_API_KEY=your_gemini_api_key_here       # gemini/...
OPENAI_API_KEY=your_openai_api_key_here       # openai/...
CEREBRAS_API_KEY=your_cerebras_api_key_here   # cerebras/...
OPENROUTER_API_KEY=your_openrouter_key_here  # openrouter/...
```

See the full list of [supported providers](https://cascadinglabs.com/reference/helpers/)


### Basic Usage

#### CLI Usage
```sh
# Specify model explicitly with -m provider:model-name
uv run yosoi -m groq:llama-3.3-70b-versatile --url https://qscrape.dev/l1/eshop/catalog/?cat=Forge%20%26%20Smithing --contract Product
```
You can then find your scraped content, selectors and logs in `./.yosoi` relative to the directory you run the CLI command from.

#### Python Usage
We also have example scripts, you can find them in our [example docs](https://cascadinglabs.com/guides/examples/)

## Citation

If you use **yosoi** in your research or projects, please cite it using the metadata provided in the `CITATION.cff` file.


<p align="center">
    <img src="media/citationExample.png" alt="Citation" width="800">
</p>
