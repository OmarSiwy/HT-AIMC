export interface PageMetadata {
  title: string
  order: number
}

export interface Page {
  id: string
  path: string
  metadata: PageMetadata
  content: string
}

export interface Section {
  id: string
  title: string
  pages: Page[]
}

// Import all content files: .ts pages export metadata + content,
// .md pages (project research docs) are raw markdown titled by their first heading
const tsModules = import.meta.glob('../content/**/*.ts', { eager: true })
const mdModules = import.meta.glob('../content/**/*.md', { eager: true, query: '?raw', import: 'default' })

const contentModules: Record<string, { metadata: PageMetadata; content: string }> = {}
for (const [path, mod] of Object.entries(tsModules)) {
  contentModules[path] = mod as { metadata: PageMetadata; content: string }
}
for (const [path, raw] of Object.entries(mdModules)) {
  const content = raw as string
  const title = content.match(/^#\s+(.+)$/m)?.[1] ?? path.split('/').pop()!.replace(/\.md$/, '')
  contentModules[path] = { metadata: { title, order: path.endsWith('/README.md') ? -1 : 0 }, content }
}

export function loadContent(): Section[] {
  const sections = new Map<string, Section>()

  for (const [path, mod] of Object.entries(contentModules)) {
    // Extract section and page from path; nested dirs become their own section
    // Example: ../content/Template/Flows/Analog.ts -> section "Template/Flows", page "Analog"
    const match = path.match(/\/content\/(.+)\/([^/]+)\.(ts|md)$/)
    if (!match) continue

    const [, sectionId, pageId] = match

    // Initialize section if it doesn't exist
    if (!sections.has(sectionId)) {
      sections.set(sectionId, {
        id: sectionId,
        title: sectionId.split('/').map(dir => dir.split('-').map(word =>
          word.charAt(0).toUpperCase() + word.slice(1)
        ).join(' ')).join(' / '),
        pages: []
      })
    }

    const section = sections.get(sectionId)!

    // Add page to section
    section.pages.push({
      id: pageId,
      path: `${sectionId}/${pageId}`,
      metadata: mod.metadata,
      content: mod.content
    })
  }

  // Sort pages within each section by order, then title
  sections.forEach(section => {
    section.pages.sort((a, b) =>
      a.metadata.order - b.metadata.order || a.metadata.title.localeCompare(b.metadata.title))
  })

  // Convert to array and sort sections: project docs first, template flow docs last
  const rank = (id: string) => id.startsWith('Template') ? 1 : 0
  return Array.from(sections.values()).sort((a, b) => {
    if (rank(a.id) !== rank(b.id)) return rank(a.id) - rank(b.id)
    // Getting-Started leads the template docs
    if (a.id.endsWith('Getting-Started')) return -1
    if (b.id.endsWith('Getting-Started')) return 1
    return a.id.localeCompare(b.id)
  })
}
