import { useState } from 'react'
import { Section } from '../utils/contentLoader'

interface SidebarProps {
  sections: Section[]
  currentPath: string
  onNavigate: (path: string) => void
}

export function Sidebar({ sections, currentPath, onNavigate }: SidebarProps) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set()  // Start with all sections collapsed
  )

  const toggleSection = (sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(sectionId)) {
        next.delete(sectionId)
      } else {
        next.add(sectionId)
      }
      return next
    })
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1 className="logo">
          <span className="logo-text">AnalogIOC</span>
        </h1>
      </div>

      <nav className="sidebar-nav">
        {sections.map(section => (
          <div key={section.id} className="nav-section">
            <button
              className="section-header"
              onClick={() => toggleSection(section.id)}
            >
              <span className={`chevron ${expandedSections.has(section.id) ? 'expanded' : ''}`}>
                ›
              </span>
              <span className="section-title">{section.title}</span>
            </button>

            {expandedSections.has(section.id) && (
              <ul className="page-list">
                {section.pages.map(page => (
                  <li key={page.path}>
                    <button
                      className={`page-link ${currentPath === page.path ? 'active' : ''}`}
                      onClick={() => onNavigate(page.path)}
                    >
                      {page.metadata.title}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </nav>
    </aside>
  )
}
