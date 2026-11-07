/** Pure helpers for rendering model Markdown safely (kept free of React so they can be unit-tested with node --test). */

/** Only http(s) and mailto links are rendered as links; anything else (javascript:, data:, relative) stays text. */
export function safeHref(url: string): string | null {
  const trimmed = url.trim()
  try {
    const parsed = new URL(trimmed)
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? parsed.href : null
  } catch {
    return null
  }
}

export type InlinePart =
  | { kind: 'text'; text: string }
  | { kind: 'bold' | 'italic' | 'code'; text: string }
  | { kind: 'link'; text: string; href: string }
  | { kind: 'cite'; n: number }

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]\n]+\]\([^)\s]+\)|\[\d+\]|\*[^*\s][^*]*\*)/g

/** Split one line of Markdown into styled parts. Citation markers [n] are kept only when n is a known source. */
export function parseInline(text: string, sourceCount = 0): InlinePart[] {
  // Models sometimes wrap math like $O(n)$ or \mathcal{O} in LaTeX; show it as plain text. A $ before a digit or space is
  // currency, never math: "$43,971.37 ... $118,447.83" must keep both dollar signs.
  const clean = text.replace(/\$(?![\d\s])([^$\n]{1,40})(?<!\s)\$/g, '$1').replace(/\\math(?:cal|rm|bf|it)\{([^}]*)\}/g, '$1')
    .replace(/\\geq?(?![A-Za-z])/g, '≥').replace(/\\leq?(?![A-Za-z])/g, '≤').replace(/\\times(?![A-Za-z])/g, '×').replace(/\\approx(?![A-Za-z])/g, '≈').replace(/\\(log|ln|exp|sqrt|max|min)(?![A-Za-z])/g, '$1')
  const parts: InlinePart[] = []
  for (const piece of clean.split(TOKEN)) {
    if (!piece) continue
    const link = /^\[([^\]\n]+)\]\(([^)\s]+)\)$/.exec(piece)
    const cite = /^\[(\d+)\]$/.exec(piece)
    if (piece.startsWith('**') && piece.endsWith('**') && piece.length > 4) parts.push({ kind: 'bold', text: piece.slice(2, -2) })
    else if (piece.startsWith('`') && piece.endsWith('`') && piece.length > 2) parts.push({ kind: 'code', text: piece.slice(1, -1) })
    else if (link) {
      const href = safeHref(link[2])
      parts.push(href ? { kind: 'link', text: link[1], href } : { kind: 'text', text: link[1] })
    } else if (cite) {
      const n = Number(cite[1])
      if (n >= 1 && n <= sourceCount) parts.push({ kind: 'cite', n })
      else if (!sourceCount) parts.push({ kind: 'text', text: piece })
    } else if (piece.startsWith('*') && piece.endsWith('*') && piece.length > 2) parts.push({ kind: 'italic', text: piece.slice(1, -1) })
    else parts.push({ kind: 'text', text: piece })
  }
  return parts
}
