"""Author Auto routing and validate it without contacting a provider."""

import yosoi as ys

policy = ys.Policy(search=ys.policy.Search.auto(["bing", "brave"]))
ys.search.new("qscrape catalog").bind(policy).check()
print(policy.to_json())
