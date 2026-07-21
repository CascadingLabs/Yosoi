/** Return regular weekly hours from the primary place panel.
 *
 * This implementation is illustrative. The API-spec concern is that the export is
 * a pure evaluator: it reads page state and returns a serializable typed value.
 */
export function extractSchedule(_args) {
  const panel = document.querySelector('[role="main"]');
  if (!panel) return null;

  const rows = Array.from(panel.querySelectorAll('[data-day]'));
  if (!rows.length) return null;

  return {
    // Never infer a timezone when the source does not explicitly publish it.
    timezone: null,
    days: Object.fromEntries(
      rows.map((row) => [
        row.getAttribute('data-day').toLowerCase(),
        row.getAttribute('data-hours') || null,
      ]),
    ),
  };
}
