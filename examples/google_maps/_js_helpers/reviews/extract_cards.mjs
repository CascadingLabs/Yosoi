import {canonicalReviewCards} from './canonical_cards.mjs';

/** Extract a bounded, serializable review-card projection. */
export function extractReviewCards({limit}) {
  return canonicalReviewCards()
    .slice(0, limit)
    .map((card, index) => {
      const profile = card.querySelector('[data-href*="/maps/contrib/"]');
      const reviewText = Array.from(card.querySelectorAll('.wiI7pd')).find(
        (element) => !element.closest('.CDe7pd'),
      );
      const ownerResponse = card.querySelector('.CDe7pd .wiI7pd');
      const ratingLabel = Array.from(card.querySelectorAll('[aria-label]'))
        .map((element) => (element.getAttribute('aria-label') || '').trim())
        .find((value) => /^\d(?:\.\d)? stars?$/i.test(value));

      return {
        review_id: card.getAttribute('data-review-id'),
        sample_rank: index + 1,
        rating: Number.parseFloat(ratingLabel || ''),
        review_text: reviewText?.innerText.trim() || null,
        relative_date: card.querySelector('.rsqaWe')?.innerText.trim() || '',
        reviewer_name:
          card.querySelector('.d4r55')?.innerText.trim() ||
          card.getAttribute('aria-label') ||
          '',
        reviewer_profile_url: profile?.getAttribute('data-href') || null,
        contribution_label: card.querySelector('.RfnDt')?.innerText.trim() || null,
        owner_response_text: ownerResponse?.innerText.trim() || null,
        owner_response_relative_date:
          card.querySelector('.DZSIDd')?.innerText.trim() || null,
      };
    });
}
