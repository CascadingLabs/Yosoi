# TodoMVC rendered-DOM dogfood

This is a frozen, policy-safe capture of the public TodoMVC JavaScript ES6 example. The live
browser episode was captured with `scripts/capture_dom_todomvc.py` through VoidCrawl after
clearing storage:

```text
S0 empty
  → add Buy milk, Read design, Ship beta
S1 three active
  → check the second todo
S2 one completed
  → select Completed
S3 completed filter
```

`capture_manifest.json` records the live HTTP status and exact artifact digests. The committed
JSON files are the test input; `test_dom_todomvc_live.py` never makes network requests. This is
dogfood evidence, not a live CI gate. Re-capture only when intentionally updating the fixture and
update the manifest/ground truth together.
