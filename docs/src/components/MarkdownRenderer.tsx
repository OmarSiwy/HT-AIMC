import React from 'react'

interface MarkdownRendererProps {
  content: string
  onNavigate?: (path: string) => void
  path?: string  // current page path, resolves relative .md links
}

// Resolve a relative .md link against the current page: "Project/A" + "campaign/B.md" -> "Project/campaign/B"
function resolveDocLink(base: string, url: string): string | null {
  const m = url.match(/^([^:#?]+)\.md(#.*)?$/)
  if (!m || url.startsWith('/')) return null
  const parts = base.split('/').slice(0, -1)
  for (const seg of m[1].split('/')) {
    if (seg === '..') parts.pop()
    else if (seg !== '.') parts.push(seg)
  }
  return '/' + parts.join('/')
}

export function MarkdownRenderer({ content, onNavigate, path = '' }: MarkdownRendererProps) {
  const lines = content.trim().split('\n')
  const elements: React.ReactNode[] = []
  let inCodeBlock = false
  let codeLines: string[] = []
  let tableRows: string[][] = []

  const splitRow = (row: string) => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())

  const processInlineMarkdown = (text: string): React.ReactNode => {
    const parts: React.ReactNode[] = []
    let remaining = text
    let key = 0

    // Process bold, inline code, and links
    const regex = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g
    const matches = remaining.match(regex)

    if (!matches) return text

    let lastIndex = 0
    matches.forEach((match) => {
      const matchIndex = remaining.indexOf(match, lastIndex)

      // Add text before match
      if (matchIndex > lastIndex) {
        parts.push(remaining.slice(lastIndex, matchIndex))
      }

      // Add the match
      if (match.startsWith('`')) {
        parts.push(<code key={key++}>{match.slice(1, -1)}</code>)
      } else if (match.startsWith('**')) {
        parts.push(<strong key={key++}>{processInlineMarkdown(match.slice(2, -2))}</strong>)
      } else if (match.startsWith('[')) {
        const linkMatch = match.match(/\[([^\]]+)\]\(([^)]+)\)/)
        if (linkMatch) {
          const [_, linkText, rawUrl] = linkMatch
          const url = resolveDocLink(path, rawUrl.replace(/^<|>$/g, '')) ?? rawUrl
          parts.push(
            <a
              key={key++}
              href={url}
              onClick={(e) => {
                if (url.startsWith('/') && onNavigate) {
                  e.preventDefault()
                  onNavigate(url)
                }
              }}
            >
              {linkText}
            </a>
          )
        }
      }

      lastIndex = matchIndex + match.length
    })

    // Add remaining text
    if (lastIndex < remaining.length) {
      parts.push(remaining.slice(lastIndex))
    }

    return parts.length > 0 ? parts : text
  }

  const flushTable = (index: number) => {
    if (tableRows.length === 0) return
    // GFM pipe table: header row, |---| separator, body rows
    const [head, ...rest] = tableRows
    const body = rest.filter(r => !r.every(c => /^:?-+:?$/.test(c)))
    elements.push(
      <table key={`table-${index}`}>
        <thead><tr>{head.map((c, i) => <th key={i}>{processInlineMarkdown(c)}</th>)}</tr></thead>
        <tbody>{body.map((r, j) => <tr key={j}>{r.map((c, i) => <td key={i}>{processInlineMarkdown(c)}</td>)}</tr>)}</tbody>
      </table>
    )
    tableRows = []
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim()

    // Tables
    if (!inCodeBlock && trimmed.startsWith('|')) {
      tableRows.push(splitRow(trimmed))
      return
    }
    flushTable(index)

    // Code blocks
    if (trimmed.startsWith('```')) {
      if (!inCodeBlock) {
        inCodeBlock = true
        codeLines = []
      } else {
        inCodeBlock = false
        elements.push(
          <pre key={`code-${index}`}>
            <code>{codeLines.join('\n')}</code>
          </pre>
        )
      }
      return
    }

    if (inCodeBlock) {
      codeLines.push(line)
      return
    }

    // Headers
    if (trimmed.startsWith('### ')) {
      elements.push(
        <h3 key={index}>
          {trimmed.slice(4)}
        </h3>
      )
      return
    }
    if (trimmed.startsWith('## ')) {
      elements.push(
        <h2 key={index}>
          {trimmed.slice(3)}
        </h2>
      )
      return
    }
    if (trimmed.startsWith('# ')) {
      elements.push(
        <h1 key={index}>
          {trimmed.slice(2)}
        </h1>
      )
      return
    }

    // Lists
    if (trimmed.startsWith('- ')) {
      elements.push(
        <li key={index}>
          {processInlineMarkdown(trimmed.slice(2))}
        </li>
      )
      return
    }
    if (trimmed.match(/^\d+\.\s/)) {
      elements.push(
        <li key={index}>
          {processInlineMarkdown(trimmed.replace(/^\d+\.\s/, ''))}
        </li>
      )
      return
    }

    // Regular paragraph
    if (trimmed) {
      elements.push(
        <p key={index}>
          {processInlineMarkdown(trimmed)}
        </p>
      )
      return
    }

    // Empty line
    elements.push(<br key={index} />)
  })
  flushTable(lines.length)

  return (
    <div className="markdown-content">
      {elements}
    </div>
  )
}
