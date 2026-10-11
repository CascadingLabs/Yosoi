# Internal document and locator implementation

This private module reads documents and finds information inside them using
typed locators. Each result keeps its location in the source document so
callers can inspect where it came from. Applications use the public
`yosoi::documents` and `yosoi::locators` namespaces.
