"""given the URL qscrape.dev do the following:
1. explore all pages of the site
2. score based on matching our 4 ys.Contracts
3. Scrape && Extract each with a max of 4 LLM calls

"""

SEED = 'qscrape.dev'


### 1. Explore all pages of the site


# ys.policy(allow all depth, urls, etc, very permissive for examsple)

# while this happens crawl handles concurrent (w/ inflight locking) fingerprinting and scraping extraction


# call site, simple

result = ys.crawl(policy, seed, contracts)


### watch the magic happen in CLI, logs, and .yosoi
#
#

ys.show(result)
