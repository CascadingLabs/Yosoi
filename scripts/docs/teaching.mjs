/** Keep conceptual prose out of executable-looking tutorial fences. */
export function validateTeachingBlocks(tree, file) {
  function visit(node) {
    if (node.type === 'code') {
      const body = node.value || '';
      if (node.lang === 'text' || /\bpseudo[ -]?code\s*:/i.test(body))
        throw new Error(`${file}: explain conceptual sequences as prose or numbered steps`);
      if (/Authoring task:|\bTODO\b|proposed (?:Python )?API/i.test(body))
        throw new Error(`${file}: unfinished or proposed code cannot be a public example`);
    }
    for (const child of node.children || []) visit(child);
  }
  visit(tree);
}
