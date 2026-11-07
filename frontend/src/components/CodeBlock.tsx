import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import scala from 'highlight.js/lib/languages/scala'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import yaml from 'highlight.js/lib/languages/yaml'
import { Check, Copy, Download } from 'lucide-react'
import { useMemo, useState } from 'react'

hljs.registerLanguage('python', python)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('scala', scala)
hljs.registerLanguage('java', java)
hljs.registerLanguage('yaml', yaml)

const ALIASES: Record<string, string> = { py: 'python', pyspark: 'python', js: 'javascript', ts: 'typescript', sh: 'bash', shell: 'bash', yml: 'yaml', sparksql: 'sql' }
const LABELS: Record<string, string> = { python: 'Python', sql: 'SQL', javascript: 'JavaScript', typescript: 'TypeScript', bash: 'Bash', json: 'JSON', scala: 'Scala', java: 'Java', yaml: 'YAML', text: 'Output', plaintext: 'Output', console: 'Output' }
const EXT: Record<string, string> = { python: 'py', sql: 'sql', javascript: 'js', typescript: 'ts', bash: 'sh', json: 'json', scala: 'scala', java: 'java', yaml: 'yaml' }

export function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false)
  const language = ALIASES[lang?.toLowerCase() ?? ''] ?? lang?.toLowerCase() ?? ''
  const html = useMemo(() => {
    try {
      return hljs.getLanguage(language) ? hljs.highlight(code, { language }).value : hljs.highlightAuto(code).value
    } catch {
      return null
    }
  }, [code, language])

  const copy = () => navigator.clipboard.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
  const download = () => {
    const url = URL.createObjectURL(new Blob([code], { type: 'text/plain' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `snippet.${EXT[language] ?? 'txt'}` })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="overflow-hidden rounded-lg bg-surface-2 ring-1 ring-line">
      <div className="flex items-center justify-between px-5 pb-1 pt-3.5">
        <span className="text-[13px] font-medium text-zinc-100">{LABELS[language] ?? (lang || 'Code')}</span>
        <div className="flex items-center gap-1 text-zinc-400">
          <button type="button" onClick={download} title="Download" aria-label="Download code" className="rounded-full p-1.5 hover:bg-zinc-800 hover:text-zinc-50">
            <Download className="h-4 w-4" />
          </button>
          <button type="button" onClick={copy} title={copied ? 'Copied' : 'Copy'} aria-label="Copy code" className="rounded-full p-1.5 hover:bg-zinc-800 hover:text-zinc-50">
            {copied ? <Check className="h-4 w-4 text-emerald-300" /> : <Copy className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <pre className="hljs overflow-x-auto px-5 pb-5 pt-3 font-mono text-[13px] leading-[1.7] text-zinc-100">
        {html !== null ? <code dangerouslySetInnerHTML={{ __html: html }} /> : <code>{code}</code>}
      </pre>
    </div>
  )
}
