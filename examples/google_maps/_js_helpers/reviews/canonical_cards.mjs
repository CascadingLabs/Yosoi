/** Select one canonical rendered node for each stable review ID. */
export function canonicalReviewCards() {
  const best = new Map();

  for (const node of document.querySelectorAll('[data-review-id]')) {
    const id = node.getAttribute('data-review-id');
    if (!id || node.innerText.trim().length < 40) continue;

    const score =
      (node.querySelector('[jsaction*=".review.share"]') ? 100 : 0) +
      (node.querySelector('[aria-label*=" stars"]') ? 10 : 0) +
      (node.querySelector('.d4r55') ? 5 : 0) +
      (Array.from(node.querySelectorAll('.wiI7pd')).some(
        (element) => !element.closest('.CDe7pd'),
      )
        ? 1
        : 0);

    const previous = best.get(id);
    if (!previous || score > previous.score) best.set(id, {node, score});
  }

  return Array.from(best.values(), ({node}) => node);
}
