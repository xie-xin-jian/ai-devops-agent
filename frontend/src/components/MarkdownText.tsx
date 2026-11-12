import { Fragment, type ReactNode } from 'react'

const INLINE_PATTERN =
  /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^)\n]+\))/g

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let cursor = 0
  let key = 0

  for (const match of text.matchAll(INLINE_PATTERN)) {
    const index = match.index ?? 0
    if (index > cursor) nodes.push(text.slice(cursor, index))
    const token = match[0]
    if (token.startsWith('`')) {
      nodes.push(<code key={key++}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={key++}>{token.slice(2, -2)}</strong>)
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
      nodes.push(
        link ? (
          <a
            key={key++}
            href={link[2]}
            target="_blank"
            rel="noreferrer"
          >
            {link[1]}
          </a>
        ) : token
      )
    }
    cursor = index + token.length
  }

  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableDivider(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line)
}

function isBlockStart(line: string): boolean {
  const value = line.trim()
  return (
    !value ||
    value.startsWith('```') ||
    /^#{1,3}\s/.test(value) ||
    value === '---' ||
    /^[-*]\s/.test(value) ||
    /^\d+\.\s/.test(value) ||
    value.startsWith('>')
  )
}

export default function MarkdownText({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]
    const trimmed = line.trim()

    if (!trimmed) {
      index += 1
      continue
    }

    if (trimmed.startsWith('```')) {
      const language = trimmed.slice(3).trim()
      const code: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        code.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(
        <div className="md-code" key={key++}>
          {language && <div className="md-code-lang">{language}</div>}
          <pre><code>{code.join('\n')}</code></pre>
        </div>
      )
      continue
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      const content = renderInline(heading[2])
      blocks.push(
        level === 1 ? (
          <h1 key={key++}>{content}</h1>
        ) : level === 2 ? (
          <h2 key={key++}>{content}</h2>
        ) : (
          <h3 key={key++}>{content}</h3>
        )
      )
      index += 1
      continue
    }

    if (trimmed === '---') {
      blocks.push(<hr key={key++} />)
      index += 1
      continue
    }

    if (
      trimmed.includes('|') &&
      index + 1 < lines.length &&
      isTableDivider(lines[index + 1])
    ) {
      const header = tableCells(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && lines[index].includes('|')) {
        rows.push(tableCells(lines[index]))
        index += 1
      }
      blocks.push(
        <div className="md-table-wrap" key={key++}>
          <table>
            <thead>
              <tr>
                {header.map((cell, cellIndex) => (
                  <th key={cellIndex}>{renderInline(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {header.map((_, cellIndex) => (
                    <td key={cellIndex}>
                      {renderInline(row[cellIndex] || '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    if (/^[-*]\s/.test(trimmed) || /^\d+\.\s/.test(trimmed)) {
      const ordered = /^\d+\.\s/.test(trimmed)
      const items: string[] = []
      const pattern = ordered ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/
      while (index < lines.length) {
        const match = lines[index].trim().match(pattern)
        if (!match) break
        items.push(match[1])
        index += 1
      }
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List key={key++}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </List>
      )
      continue
    }

    if (trimmed.startsWith('>')) {
      const quote: string[] = []
      while (index < lines.length && lines[index].trim().startsWith('>')) {
        quote.push(lines[index].trim().replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={key++}>{renderInline(quote.join(' '))}</blockquote>
      )
      continue
    }

    const paragraph = [line]
    index += 1
    while (
      index < lines.length &&
      !isBlockStart(lines[index]) &&
      !(
        lines[index].trim().includes('|') &&
        index + 1 < lines.length &&
        isTableDivider(lines[index + 1])
      )
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(
      <p key={key++}>
        {paragraph.map((part, partIndex) => (
          <Fragment key={partIndex}>
            {partIndex > 0 && '\n'}
            {renderInline(part)}
          </Fragment>
        ))}
      </p>
    )
  }

  return <>{blocks}</>
}
