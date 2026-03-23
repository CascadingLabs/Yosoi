"""Generate realistic mock HTML fixtures for benchmarking the cleaner."""

from pathlib import Path

HERE = Path(__file__).parent


def _ecommerce_listing(n_products: int = 60) -> str:
    """Simulate a Tailwind-heavy e-commerce product listing page (~200KB)."""
    cards = []
    for i in range(n_products):
        cards.append(f"""\
        <div class="flex flex-col bg-white rounded-lg shadow-md overflow-hidden hover:shadow-xl transition-shadow duration-300 p-4 m-2 w-full sm:w-1/2 md:w-1/3 lg:w-1/4 product-card" data-product-id="{i}">
          <div class="relative overflow-hidden rounded-t-lg">
            <img src="data:image/png;base64,{'A' * 200}" alt="Product {i}" class="w-full h-48 object-cover transform hover:scale-105 transition-transform duration-300"/>
            <span class="absolute top-2 right-2 bg-red-500 text-white text-xs font-bold px-2 py-1 rounded-full">SALE</span>
          </div>
          <div class="flex flex-col flex-1 p-4 space-y-2">
            <h3 class="text-lg font-semibold text-gray-900 line-clamp-2 product-title">Premium Widget Model {i} - Professional Grade</h3>
            <div class="flex items-center space-x-1">
              <svg viewBox="0 0 20 20" class="w-4 h-4 text-yellow-400"><path d="M10 15l-5.878 3.09L5.245 12.18.367 8.41l6.122-.89L10 2l3.511 5.52 6.122.89-4.878 3.77 1.123 5.91z"/></svg>
              <svg viewBox="0 0 20 20" class="w-4 h-4 text-yellow-400"><path d="M10 15l-5.878 3.09L5.245 12.18.367 8.41l6.122-.89L10 2l3.511 5.52 6.122.89-4.878 3.77 1.123 5.91z"/></svg>
              <svg viewBox="0 0 20 20" class="w-4 h-4 text-yellow-400"><path d="M10 15l-5.878 3.09L5.245 12.18.367 8.41l6.122-.89L10 2l3.511 5.52 6.122.89-4.878 3.77 1.123 5.91z"/></svg>
              <svg viewBox="0 0 20 20" class="w-4 h-4 text-yellow-400"><path d="M10 15l-5.878 3.09L5.245 12.18.367 8.41l6.122-.89L10 2l3.511 5.52 6.122.89-4.878 3.77 1.123 5.91z"/></svg>
              <svg viewBox="0 0 20 20" class="w-4 h-4 text-gray-300"><path d="M10 15l-5.878 3.09L5.245 12.18.367 8.41l6.122-.89L10 2l3.511 5.52 6.122.89-4.878 3.77 1.123 5.91z"/></svg>
              <span class="text-sm text-gray-500 ml-1 review-count">({42 + i} reviews)</span>
            </div>
            <p class="text-sm text-gray-600 line-clamp-3 product-description">
              High-quality widget designed for professional use. Features advanced materials,
              precision engineering, and a {i}-year warranty. Perfect for demanding applications.
            </p>
            <div class="flex items-center justify-between mt-auto pt-2 border-t border-gray-100">
              <div class="flex flex-col">
                <span class="text-xs text-gray-400 line-through original-price">${99.99 + i:.2f}</span>
                <span class="text-xl font-bold text-green-600 sale-price">${(99.99 + i) * 0.8:.2f}</span>
              </div>
              <button class="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 add-to-cart" data-id="{i}">
                Add to Cart
              </button>
            </div>
          </div>
        </div>""")

    sidebar_links = '\n'.join(
        f'<li class="py-1"><a href="/category/{i}" class="text-blue-600 hover:text-blue-800 text-sm transition-colors">Category {i}</a></li>'
        for i in range(30)
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <title>Shop - Premium Widgets</title>
    <script>
        window.__NEXT_DATA__ = {{"props": {{"pageProps": {{}}}}}};
        (function(){{ var gtag = document.createElement('script'); gtag.async = true; }})();
    </script>
    <style>
        .product-card {{ transition: all 0.3s ease; }}
        @media (max-width: 768px) {{ .product-card {{ width: 100%; }} }}
        /* 500 lines of CSS would go here */
        {'/* padding */' * 200}
    </style>
    <link rel="stylesheet" href="/styles/tailwind.css"/>
</head>
<body class="bg-gray-50 min-h-screen">
    <nav class="bg-white shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16 items-center">
                <a href="/" class="flex items-center space-x-2">
                    <span class="text-xl font-bold text-gray-900">WidgetShop</span>
                </a>
                <div class="hidden md:flex items-center space-x-8">
                    <a href="/products" class="text-gray-600 hover:text-gray-900">Products</a>
                    <a href="/deals" class="text-gray-600 hover:text-gray-900">Deals</a>
                    <a href="/about" class="text-gray-600 hover:text-gray-900">About</a>
                </div>
                <div class="flex items-center space-x-4">
                    <button class="relative p-2 text-gray-600 hover:text-gray-900" aria-label="Cart">
                        <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z"/></svg>
                        <span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">3</span>
                    </button>
                </div>
            </div>
        </div>
    </nav>

    <header class="bg-gradient-to-r from-blue-600 to-blue-800 text-white py-12">
        <div class="max-w-7xl mx-auto px-4">
            <h1 class="text-4xl font-bold">Premium Widgets</h1>
            <p class="mt-2 text-blue-100">Discover our collection of {n_products} professional-grade widgets</p>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 py-8">
        <div class="flex flex-col lg:flex-row gap-8">
            <!-- Sidebar filters -->
            <aside class="sidebar w-full lg:w-64 flex-shrink-0">
                <div class="bg-white rounded-lg shadow p-4 sticky top-24">
                    <h2 class="font-bold text-lg mb-4">Filters</h2>
                    <div class="space-y-4">
                        <div>
                            <h3 class="font-medium text-sm text-gray-700 mb-2">Categories</h3>
                            <ul class="space-y-1">{sidebar_links}</ul>
                        </div>
                        <div>
                            <h3 class="font-medium text-sm text-gray-700 mb-2">Price Range</h3>
                            <input type="range" min="0" max="500" class="w-full"/>
                        </div>
                    </div>
                </div>
            </aside>

            <!-- Product grid -->
            <div class="flex-1">
                <div class="flex flex-wrap -m-2 product-grid">
                    {''.join(cards)}
                </div>
            </div>
        </div>
    </main>

    <footer class="bg-gray-900 text-gray-400 py-12 mt-16">
        <div class="max-w-7xl mx-auto px-4 grid grid-cols-1 md:grid-cols-4 gap-8">
            <div><h4 class="text-white font-bold mb-4">Company</h4><ul class="space-y-2">{''.join(f'<li><a href="#">Link {i}</a></li>' for i in range(8))}</ul></div>
            <div><h4 class="text-white font-bold mb-4">Support</h4><ul class="space-y-2">{''.join(f'<li><a href="#">Help {i}</a></li>' for i in range(6))}</ul></div>
            <div><h4 class="text-white font-bold mb-4">Legal</h4><ul class="space-y-2">{''.join(f'<li><a href="#">Legal {i}</a></li>' for i in range(4))}</ul></div>
            <div><h4 class="text-white font-bold mb-4">Social</h4><p class="text-sm">Follow us on social media</p></div>
        </div>
    </footer>

    <script src="/js/analytics.js"></script>
    <script>
        // tracking pixel
        {'console.log("track");' * 50}
    </script>
    <noscript><img src="/pixel.gif" alt=""/></noscript>
</body>
</html>"""


def _blog_article() -> str:
    """Simulate a content-heavy blog/news article page (~80KB)."""
    paragraphs = []
    for i in range(25):
        paragraphs.append(f"""\
        <p class="text-base leading-relaxed text-gray-700 mb-4">
            Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor
            incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud
            exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Paragraph {i}
            continues with more analysis of the topic at hand, drawing from expert sources
            and recent developments in the field. The implications are far-reaching and
            merit careful consideration by stakeholders across multiple industries.
        </p>""")

    comments = []
    for i in range(20):
        comments.append(f"""\
        <div class="comment border-l-4 border-gray-200 pl-4 mb-4">
            <div class="flex items-center space-x-2 mb-1">
                <img src="data:image/png;base64,{'B' * 100}" alt="avatar" class="w-8 h-8 rounded-full"/>
                <span class="font-medium text-sm comment-author">User{i}</span>
                <time datetime="2025-01-{i + 1:02d}" class="text-xs text-gray-400">Jan {i + 1}, 2025</time>
            </div>
            <p class="text-sm text-gray-600">This is comment {i}. Great article, very insightful analysis!</p>
        </div>""")

    related = '\n'.join(
        f'<li class="related-posts"><a href="/post/{i}" class="text-blue-600 hover:underline">Related Article {i}: More Analysis</a></li>'
        for i in range(10)
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <title>In-Depth Analysis: The Future of Technology - TechBlog</title>
    <script type="application/ld+json">
    {{
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": "In-Depth Analysis: The Future of Technology",
        "author": {{"@type": "Person", "name": "Jane Smith"}},
        "datePublished": "2025-01-15",
        "image": "https://example.com/hero.jpg"
    }}
    </script>
    <style>{'/* styles */' * 100}</style>
    <script>{'/* analytics */' * 50}</script>
</head>
<body>
    <nav class="bg-white border-b">
        <div class="max-w-4xl mx-auto flex justify-between py-4 px-4">
            <a href="/" class="font-bold text-xl">TechBlog</a>
            <div class="flex space-x-4">
                <a href="/tech">Tech</a><a href="/science">Science</a><a href="/opinion">Opinion</a>
            </div>
        </div>
    </nav>

    <main class="max-w-4xl mx-auto px-4 py-8">
        <article class="article-content" data-article-id="12345">
            <header class="mb-8">
                <h1 class="text-4xl font-bold text-gray-900 mb-4 article-title">In-Depth Analysis: The Future of Technology</h1>
                <div class="flex items-center space-x-4 text-sm text-gray-500">
                    <span class="author-name font-medium">By Jane Smith</span>
                    <time datetime="2025-01-15" class="publish-date">January 15, 2025</time>
                    <span class="reading-time">12 min read</span>
                </div>
                <div class="flex space-x-2 mt-4">
                    <span class="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded article-tag">Technology</span>
                    <span class="bg-green-100 text-green-800 text-xs px-2 py-1 rounded article-tag">Innovation</span>
                </div>
            </header>

            <figure class="mb-8">
                <img src="https://example.com/hero.jpg" alt="Hero image" class="w-full rounded-lg hero-image"/>
                <figcaption class="text-sm text-gray-500 mt-2 image-caption">Photo by John Doe / Unsplash</figcaption>
            </figure>

            <div class="article-body prose prose-lg max-w-none">
                {''.join(paragraphs)}

                <blockquote class="border-l-4 border-blue-500 pl-4 italic text-gray-600 my-6 pull-quote">
                    "The convergence of AI and quantum computing will reshape every industry
                    within the next decade." — Dr. Alex Johnson, MIT
                </blockquote>

                <h2 class="text-2xl font-bold mt-8 mb-4 section-heading">Key Takeaways</h2>
                <ul class="list-disc pl-6 space-y-2 mb-6 key-points">
                    <li>Point 1: Technology adoption is accelerating exponentially</li>
                    <li>Point 2: Privacy concerns remain a critical challenge</li>
                    <li>Point 3: Regulation is lagging behind innovation</li>
                    <li>Point 4: Cross-industry collaboration is essential</li>
                    <li>Point 5: Education systems must adapt rapidly</li>
                </ul>

                <table class="w-full border-collapse mb-6 data-table">
                    <thead><tr class="bg-gray-100"><th class="border p-2">Year</th><th class="border p-2">Investment ($B)</th><th class="border p-2">Growth</th></tr></thead>
                    <tbody>
                        {''.join(f'<tr><td class="border p-2">{2020 + i}</td><td class="border p-2">{50 + i * 15}</td><td class="border p-2">{10 + i * 3}%</td></tr>' for i in range(8))}
                    </tbody>
                </table>
            </div>
        </article>

        <!-- Comments section -->
        <section class="mt-12 border-t pt-8 comments-section">
            <h2 class="text-2xl font-bold mb-6">Comments ({len(comments)})</h2>
            {''.join(comments)}
        </section>

        <!-- Related posts -->
        <aside class="mt-8 bg-gray-50 rounded-lg p-6">
            <h3 class="font-bold mb-4">Related Articles</h3>
            <ul class="space-y-2">{related}</ul>
        </aside>
    </main>

    <footer class="bg-gray-900 text-white py-8 mt-16">
        <div class="max-w-4xl mx-auto px-4 text-center">
            <p>&copy; 2025 TechBlog. All rights reserved.</p>
        </div>
    </footer>

    <div class="advertisement fixed bottom-0 w-full bg-yellow-100 p-4 text-center" id="ad-banner">
        <p>Subscribe for premium content!</p>
    </div>
    <div hidden aria-hidden="true" class="modal-overlay">
        <div class="modal-content">Hidden modal content that should be removed</div>
    </div>
</body>
</html>"""


def _spa_heavy() -> str:
    """Simulate a React/Next.js SPA with deeply nested wrapper divs (~150KB)."""

    def _nested_wrappers(content: str, depth: int = 8) -> str:
        result = content
        for _ in range(depth):
            result = f'<div><div>{result}</div></div>'
        return result

    items = []
    for i in range(40):
        inner = f"""\
<div class="flex items-center justify-between p-4 border-b border-gray-100">
    <div class="flex items-center space-x-3">
        <div><div><div>
            <img src="data:image/jpeg;base64,{'C' * 150}" class="w-10 h-10 rounded-full"/>
        </div></div></div>
        <div>
            <div><div>
                <span class="font-medium text-sm result-title">Search Result {i}: Professional Widget</span>
            </div></div>
            <div><div><div>
                <span class="text-xs text-gray-400 result-meta">Updated 2 hours ago &middot; 4.{i} stars</span>
            </div></div></div>
        </div>
    </div>
    <div><div>
        <span class="text-lg font-bold text-gray-900 result-price">${19.99 + i:.2f}</span>
    </div></div>
</div>"""
        items.append(_nested_wrappers(inner, depth=3))

    # Generate a big chunk of empty/decorative divs (common in SPAs)
    decorative = '<div><div><div><span></span></div></div></div>' * 50

    return f"""\
<!DOCTYPE html>
<html>
<head>
    <title>Search Results - AppName</title>
    <script>
        window.__NEXT_DATA__ = {{"buildId": "abc123", "props": {{"pageProps": {{"results": []}}}}}};
        {'console.log("hydrate");' * 30}
    </script>
    <style>
        {'/* generated styles */ .cls-abc { display: flex; } ' * 100}
    </style>
</head>
<body>
    <div id="__next">
        <div><div><div>
            <nav>
                <div class="flex justify-between p-4">
                    <span class="font-bold">AppName</span>
                    <div class="flex space-x-4">
                        <a href="/search">Search</a>
                        <a href="/account">Account</a>
                    </div>
                </div>
            </nav>
        </div></div></div>

        <div><div><div><div>
            <main class="max-w-3xl mx-auto">
                <div><div>
                    <h1 class="text-2xl font-bold p-4 search-heading">Search Results for "widgets"</h1>
                </div></div>

                <div class="search-results">
                    {''.join(items)}
                </div>

                <!-- Decorative/empty wrapper noise -->
                {decorative}

                <!-- Pagination -->
                <div class="flex justify-center p-4 pagination">
                    {''.join(f'<a href="/search?page={i}" class="px-3 py-1 mx-1 border rounded text-sm">{i}</a>' for i in range(1, 11))}
                </div>
            </main>
        </div></div></div></div>

        <div><div><div>
            <footer class="bg-gray-100 p-8 mt-8">
                <p class="text-center text-gray-500 text-sm">&copy; 2025 AppName</p>
            </footer>
        </div></div></div>
    </div>

    <canvas id="confetti-canvas" width="1920" height="1080"></canvas>
    <svg class="hidden" aria-hidden="true">
        <defs>{''.join(f'<symbol id="icon-{i}"><path d="M0 0h24v24H0z"/></symbol>' for i in range(20))}</defs>
    </svg>
    <noscript>Please enable JavaScript</noscript>
</body>
</html>"""


def generate_all() -> None:
    """Write all fixture HTML files."""
    fixtures = {
        'ecommerce_listing.html': _ecommerce_listing(),
        'blog_article.html': _blog_article(),
        'spa_heavy.html': _spa_heavy(),
    }
    for name, html in fixtures.items():
        path = HERE / name
        path.write_text(html, encoding='utf-8')
        print(f'  wrote {name}: {len(html):,} chars ({len(html) / 1024:.0f} KB)')


if __name__ == '__main__':
    generate_all()
