# Internal browser provider

This private module owns Yosoi's Chromium browser session, page actions,
browser document capture, and cleanup. Its historical controller identity is
`yosoi-browser-core`; applications use the public `yosoi` browser feature and
do not import this implementation module directly.
