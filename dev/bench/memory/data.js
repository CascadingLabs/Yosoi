window.BENCHMARK_DATA = {
  "lastUpdate": 1781690347593,
  "repoUrl": "https://github.com/CascadingLabs/Yosoi",
  "entries": {
    "voidcrawl memory (PSS)": [
      {
        "commit": {
          "author": {
            "name": "Andrew Berg",
            "username": "AndrewPBerg",
            "email": "158314138+AndrewPBerg@users.noreply.github.com"
          },
          "committer": {
            "name": "GitHub",
            "username": "web-flow",
            "email": "noreply@github.com"
          },
          "id": "96b8656b37be409d940665d54ba941de12190185",
          "message": "Update memory-bench.yaml (#101)",
          "timestamp": "2026-06-17T09:54:05Z",
          "url": "https://github.com/CascadingLabs/Yosoi/commit/96b8656b37be409d940665d54ba941de12190185"
        },
        "date": 1781690345902,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "voidcrawl base idle",
            "value": 556.9,
            "unit": "MB"
          },
          {
            "name": "voidcrawl L1 static per-tab",
            "value": 39.4,
            "unit": "MB/tab"
          },
          {
            "name": "voidcrawl L1 static fixed overhead",
            "value": 686,
            "unit": "MB"
          },
          {
            "name": "voidcrawl L2 SPA per-tab",
            "value": 40.5,
            "unit": "MB/tab"
          },
          {
            "name": "voidcrawl L2 SPA fixed overhead",
            "value": 624.3,
            "unit": "MB"
          },
          {
            "name": "voidcrawl post-teardown residue",
            "value": 100.7,
            "unit": "MB"
          }
        ]
      }
    ]
  }
}