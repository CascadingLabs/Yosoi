/** Read the public URL from the currently open Share-review dialog. */
export function readShareUrl(_args) {
  const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find(
    (element) => /Review of/.test(element.innerText),
  );
  return dialog?.querySelector('input')?.value || null;
}
