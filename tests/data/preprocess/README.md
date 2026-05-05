# Preprocess fixtures

Six representative HTML samples used by the CAS-18 spike to validate the
tier-1 + tier-2 preprocessor. Each captures a different pattern observed
on real pages:

| File | Pattern |
| --- | --- |
| `vue_spa.html` | Vue SPA with `data-v-*` scoped attrs and inline styles |
| `react_app.html` | React app with `data-reactroot`, event handlers, hydration JSON |
| `angular_dashboard.html` | Angular app with `_ngcontent-*`, `ng-*` directives |
| `wordpress_article.html` | WordPress article with JSON-LD, comments, inline styles |
| `next_js_product.html` | Next.js product page with massive `__NEXT_DATA__` payload |
| `svg_heavy_chart.html` | Page dominated by inline SVG geometry |

These are small synthetic samples (≤ 8KB each) that exercise every transform
without depending on network access or licensed content.
