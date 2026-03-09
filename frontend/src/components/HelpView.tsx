'use client';
import { useEffect, useRef } from 'react';
import { helpSections } from '../data/helpData';
import { tourList, toursBySection } from '../data/tourSteps';
import '../styles/help.css';
import '../styles/guided-tour.css';

interface HelpViewProps {
  scrollToSection?: string;
  onClose: () => void;
  onStartTour?: (tourId: string) => void;
}

export default function HelpView({ scrollToSection, onClose, onStartTour }: HelpViewProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (scrollToSection) {
      // Try entry-level scroll first (e.g. "toolbar.submit" → scroll to that card)
      const entryEl = document.getElementById(`help-entry-${scrollToSection}`);
      if (entryEl) {
        entryEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        entryEl.classList.add('help-entry-highlight');
        setTimeout(() => entryEl.classList.remove('help-entry-highlight'), 2000);
        return;
      }
      // Fall back to section-level scroll
      const sectionId = scrollToSection.split('.')[0];
      const el = sectionRefs.current[sectionId];
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }, [scrollToSection]);

  const handleSidebarClick = (sectionId: string) => {
    const el = sectionRefs.current[sectionId];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="help-view">
      <div className="help-sidebar">
        <div className="help-sidebar-title">Sections</div>
        {onStartTour && (
          <button
            className="help-sidebar-item"
            onClick={() => handleSidebarClick('guided-tours')}
          >
            Guided Tours
          </button>
        )}
        {helpSections.map((s) => (
          <button
            key={s.id}
            className="help-sidebar-item"
            onClick={() => handleSidebarClick(s.id)}
          >
            {s.title}
          </button>
        ))}
      </div>
      <div className="help-content" ref={contentRef}>
        <div className="help-header">
          <h2 className="help-title">LoomAI — Help</h2>
          <button className="help-back-btn" onClick={onClose}>
            Back
          </button>
        </div>

        {/* Guided Tours section */}
        {onStartTour && (
          <div
            className="help-section"
            ref={(el) => { sectionRefs.current['guided-tours'] = el; }}
          >
            <h3 className="help-section-title">Guided Tours</h3>
            <div className="help-tours-grid">
              {tourList.map((tour) => (
                <div key={tour.id} className="help-tour-card">
                  <div className="help-tour-card-icon">{tour.icon}</div>
                  <div className="help-tour-card-title">{tour.title}</div>
                  <div className="help-tour-card-desc">{tour.description}</div>
                  <button
                    className="help-tour-btn"
                    onClick={() => onStartTour(tour.id)}
                  >
                    Start Tour
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {helpSections.map((section) => {
          const sectionTours = toursBySection[section.id];
          return (
            <div
              key={section.id}
              className="help-section"
              ref={(el) => { sectionRefs.current[section.id] = el; }}
            >
              <h3 className="help-section-title">{section.title}</h3>
              {onStartTour && sectionTours && sectionTours.length > 0 && (
                <div className="help-inline-tours">
                  {sectionTours.map((tour) => (
                    <button
                      key={tour.id}
                      className="help-inline-tour-btn"
                      onClick={() => onStartTour(tour.id)}
                    >
                      {tour.icon} Take the {tour.title} Tour
                    </button>
                  ))}
                </div>
              )}
              {section.entries.map((entry) => (
                <div key={entry.id} className="help-entry-card" id={`help-entry-${entry.id}`}>
                  <h4 className="help-entry-label">{entry.label}</h4>
                  <p className="help-entry-desc">{entry.description}</p>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
