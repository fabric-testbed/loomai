'use client';
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import * as api from '../api/client';
import type { SiteInfo, CalendarData, CalendarSite, CalendarSlice, NextAvailableResult, AlternativeResult, Reservation } from '../types/fabric';
import type { SliceSummary } from '../types/fabric';
import '../styles/resource-calendar.css';

const GPU_OPTIONS = ['None', 'GPU_RTX6000', 'GPU_TeslaT4', 'GPU_A30', 'GPU_A40'];

interface ResourceCalendarProps {
  sites: SiteInfo[];
  slices?: SliceSummary[];
}

function formatDay(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function ResourceCalendar({ sites, slices = [] }: ResourceCalendarProps) {
  const [calendarData, setCalendarData] = useState<CalendarData | null>(null);
  const [calLoading, setCalLoading] = useState(false);
  const [calError, setCalError] = useState('');

  // Finder state
  const [finderOpen, setFinderOpen] = useState(false);
  const [fCores, setFCores] = useState<number | ''>('');
  const [fRam, setFRam] = useState<number | ''>('');
  const [fDisk, setFDisk] = useState<number | ''>('');
  const [fGpu, setFGpu] = useState('None');
  const [fSite, setFSite] = useState('');
  const [finderLoading, setFinderLoading] = useState(false);
  const [nextResult, setNextResult] = useState<NextAvailableResult | null>(null);
  const [altResult, setAltResult] = useState<AlternativeResult | null>(null);

  // Tooltip
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  // Reservation scheduling state
  const [schedOpen, setSchedOpen] = useState(false);
  const [schedSlice, setSchedSlice] = useState('');
  const [schedTime, setSchedTime] = useState('');
  const [schedDuration, setSchedDuration] = useState(24);
  const [schedAutoSubmit, setSchedAutoSubmit] = useState(true);
  const [schedLoading, setSchedLoading] = useState(false);
  const [reservations, setReservations] = useState<api.Reservation[]>([]);

  const timelineRef = useRef<HTMLDivElement>(null);

  // Fetch calendar data
  const loadCalendar = useCallback(async () => {
    setCalLoading(true);
    setCalError('');
    try {
      const data = await api.getScheduleCalendar(14);
      setCalendarData(data);
    } catch (err: unknown) {
      setCalError(err instanceof Error ? err.message : 'Failed to load calendar');
    } finally {
      setCalLoading(false);
    }
  }, []);

  useEffect(() => { loadCalendar(); }, [loadCalendar]);

  // Load reservations
  const loadReservations = useCallback(async () => {
    try {
      const data = await api.listReservations();
      setReservations(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadReservations(); }, [loadReservations]);

  const handleSchedule = useCallback(async () => {
    if (!schedSlice || !schedTime) return;
    setSchedLoading(true);
    try {
      await api.createReservation({
        slice_name: schedSlice,
        scheduled_time: new Date(schedTime).toISOString(),
        duration_hours: schedDuration,
        auto_submit: schedAutoSubmit,
      });
      setSchedSlice('');
      setSchedTime('');
      await loadReservations();
    } catch (err: unknown) {
      // surface error in calendar error area
      setCalError(err instanceof Error ? err.message : 'Failed to create reservation');
    } finally {
      setSchedLoading(false);
    }
  }, [schedSlice, schedTime, schedDuration, schedAutoSubmit, loadReservations]);

  const handleCancelReservation = useCallback(async (id: string) => {
    try {
      await api.deleteReservation(id);
      await loadReservations();
    } catch { /* ignore */ }
  }, [loadReservations]);

  // Finder search
  const handleFind = useCallback(async () => {
    setFinderLoading(true);
    setNextResult(null);
    setAltResult(null);
    try {
      const params: { cores?: number; ram?: number; disk?: number; gpu?: string; site?: string } = {};
      if (fCores) params.cores = fCores;
      if (fRam) params.ram = fRam;
      if (fDisk) params.disk = fDisk;
      if (fGpu !== 'None') params.gpu = fGpu;
      if (fSite) params.site = fSite;
      const result = await api.findNextAvailable(params);
      setNextResult(result);

      // If a preferred site was selected and is not in available_now, fetch alternatives
      if (fSite && !result.available_now.some(a => a.site === fSite)) {
        const altParams: { cores?: number; ram?: number; disk?: number; gpu?: string; preferred_site: string } = {
          preferred_site: fSite,
        };
        if (fCores) altParams.cores = fCores;
        if (fRam) altParams.ram = fRam;
        if (fDisk) altParams.disk = fDisk;
        if (fGpu !== 'None') altParams.gpu = fGpu;
        try {
          const alt = await api.getAlternatives(altParams);
          setAltResult(alt);
        } catch { /* ignore alternatives error */ }
      }
    } catch (err: unknown) {
      // Show error inline
      setNextResult({ available_now: [], available_soon: [], not_available: [{ site: '*', reason: err instanceof Error ? err.message : 'Search failed' }] });
    } finally {
      setFinderLoading(false);
    }
  }, [fCores, fRam, fDisk, fGpu, fSite]);

  // Sorted sites
  const sortedSites = useMemo(() => {
    if (!calendarData) return [];
    return [...calendarData.sites].sort((a, b) => a.name.localeCompare(b.name));
  }, [calendarData]);

  // Time range
  const rangeStart = calendarData ? new Date(calendarData.time_range.start).getTime() : 0;
  const rangeEnd = calendarData ? new Date(calendarData.time_range.end).getTime() : 0;
  const rangeDuration = rangeEnd - rangeStart;
  const now = Date.now();

  // Day columns
  const days = useMemo(() => {
    if (!rangeDuration) return [];
    const result: Date[] = [];
    const d = new Date(rangeStart);
    d.setHours(0, 0, 0, 0);
    const end = new Date(rangeEnd);
    while (d <= end) {
      result.push(new Date(d));
      d.setDate(d.getDate() + 1);
    }
    return result;
  }, [rangeStart, rangeEnd, rangeDuration]);

  const numDays = days.length;

  // Bar position calculator
  const barStyle = useCallback((slice: CalendarSlice) => {
    if (!rangeDuration) return null;
    const leaseEnd = new Date(slice.lease_end).getTime();
    // Use "now" as start if we don't have a lease_start
    const barStart = Math.max(rangeStart, now);
    const barEnd = Math.min(leaseEnd, rangeEnd);
    if (barEnd <= barStart) return null;
    const left = ((barStart - rangeStart) / rangeDuration) * 100;
    const width = ((barEnd - barStart) / rangeDuration) * 100;
    if (width < 0.1) return null;
    return { left: `${left}%`, width: `${width}%` };
  }, [rangeStart, rangeEnd, rangeDuration, now]);

  // Bar class
  const barClass = useCallback((slice: CalendarSlice) => {
    const leaseEnd = new Date(slice.lease_end).getTime();
    const state = slice.state.toLowerCase();
    if (state.includes('dead') || state.includes('closing')) return 'rc-bar past';
    if (leaseEnd - now < 24 * 60 * 60 * 1000) return 'rc-bar expiring';
    return 'rc-bar';
  }, [now]);

  // Tooltip text for a bar
  const barTooltipText = useCallback((slice: CalendarSlice) => {
    const totalCores = slice.nodes.reduce((s, n) => s + n.cores, 0);
    const totalRam = slice.nodes.reduce((s, n) => s + n.ram, 0);
    return `${slice.name}\nState: ${slice.state}\nLease end: ${formatDateTime(slice.lease_end)}\n${slice.nodes.length} node${slice.nodes.length !== 1 ? 's' : ''} \u00d7 ${totalCores} cores / ${totalRam} GB RAM`;
  }, []);

  // Now-line position
  const nowLeft = rangeDuration ? ((now - rangeStart) / rangeDuration) * 100 : 0;
  const showNowLine = nowLeft >= 0 && nowLeft <= 100;

  // Site names from props for the finder dropdown
  const siteNames = useMemo(() => sites.map(s => s.name).sort(), [sites]);

  if (calError && !calendarData) {
    return (
      <div className="rc-container">
        <div className="rc-empty">{calError} <button onClick={loadCalendar} style={{ marginLeft: 8 }}>Retry</button></div>
      </div>
    );
  }

  return (
    <div className="rc-container">
      {/* Finder toggle */}
      <div className="rc-finder-toggle" onClick={() => setFinderOpen(o => !o)}>
        <span className={`rc-chevron ${finderOpen ? 'open' : ''}`}>{'\u25B6'}</span>
        Find Available Resources
      </div>

      {/* Finder panel */}
      {finderOpen && (
        <div className="rc-finder">
          <div className="rc-finder-form">
            <div className="rc-finder-field">
              <label>Cores</label>
              <input type="number" min={1} value={fCores} onChange={e => setFCores(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
            </div>
            <div className="rc-finder-field">
              <label>RAM (GB)</label>
              <input type="number" min={1} value={fRam} onChange={e => setFRam(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
            </div>
            <div className="rc-finder-field">
              <label>Disk (GB)</label>
              <input type="number" min={1} value={fDisk} onChange={e => setFDisk(e.target.value ? Number(e.target.value) : '')} placeholder="Any" />
            </div>
            <div className="rc-finder-field">
              <label>GPU</label>
              <select value={fGpu} onChange={e => setFGpu(e.target.value)}>
                {GPU_OPTIONS.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            <div className="rc-finder-field">
              <label>Site</label>
              <select value={fSite} onChange={e => setFSite(e.target.value)}>
                <option value="">Any</option>
                {siteNames.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <button className="rc-finder-btn" onClick={handleFind} disabled={finderLoading}>
              {finderLoading ? 'Searching...' : 'Find'}
            </button>
          </div>

          {/* Results */}
          {nextResult && (
            <div className="rc-finder-results">
              {nextResult.available_now.length > 0 && (
                <>
                  <h4>Available Now</h4>
                  <div>
                    {nextResult.available_now.map(a => (
                      <span key={a.site} className="rc-available-badge" title={`${a.cores_available} cores, ${a.ram_available} GB RAM`}>
                        {a.site}
                      </span>
                    ))}
                  </div>
                </>
              )}
              {nextResult.available_soon.length > 0 && (
                <>
                  <h4>Available Soon</h4>
                  <div>
                    {nextResult.available_soon.map(a => (
                      <span key={a.site}>
                        <span className="rc-available-badge soon">{a.site}</span>
                        <span className="rc-soon-detail">
                          {formatDateTime(a.earliest_time)}
                          {a.freeing_slices.length > 0 && ` (${a.freeing_slices.map(s => s.name).join(', ')} expiring)`}
                        </span>
                      </span>
                    ))}
                  </div>
                </>
              )}
              {nextResult.not_available.length > 0 && (
                <>
                  <h4>Not Available</h4>
                  <div>
                    {nextResult.not_available.map(a => (
                      <span key={a.site} className="rc-available-badge unavailable" title={a.reason}>
                        {a.site}
                      </span>
                    ))}
                  </div>
                </>
              )}

              {/* Alternatives */}
              {altResult && altResult.alternatives.length > 0 && (
                <div className="rc-alternatives">
                  <h4>Alternatives for {altResult.preferred_site}</h4>
                  <div>
                    {altResult.alternatives.map((alt, i) => (
                      <div key={i} className="rc-alternative-card">
                        <span className="rc-alt-type">{alt.type.replace(/_/g, ' ')}</span>
                        <span className="rc-alt-site">{alt.site}</span>
                        {alt.available_now !== undefined && (
                          <span className="rc-alt-detail">{alt.available_now ? 'Available now' : 'Unavailable'}</span>
                        )}
                        {alt.cores_available !== undefined && (
                          <span className="rc-alt-detail">{alt.cores_available} cores, {alt.ram_available} GB</span>
                        )}
                        {alt.suggestion && <span className="rc-alt-detail">{alt.suggestion}</span>}
                        {alt.earliest_time && <span className="rc-alt-detail">Available: {formatDateTime(alt.earliest_time)}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Schedule Submission toggle */}
      <div className="rc-finder-toggle" onClick={() => setSchedOpen(o => !o)}>
        <span className={`rc-chevron ${schedOpen ? 'open' : ''}`}>{'\u25B6'}</span>
        Schedule Submission
      </div>

      {schedOpen && (
        <div className="rc-finder">
          <div className="rc-finder-form">
            <div className="rc-finder-field">
              <label>Slice</label>
              <select value={schedSlice} onChange={e => setSchedSlice(e.target.value)} style={{ width: 160 }}>
                <option value="">-- Select slice --</option>
                {slices.map(s => <option key={s.id || s.name} value={s.name}>{s.name}</option>)}
              </select>
            </div>
            <div className="rc-finder-field">
              <label>Scheduled Time</label>
              <input type="datetime-local" value={schedTime} onChange={e => setSchedTime(e.target.value)} style={{ width: 180 }} />
            </div>
            <div className="rc-finder-field">
              <label>Duration (hrs)</label>
              <input type="number" min={1} max={720} value={schedDuration} onChange={e => setSchedDuration(Number(e.target.value) || 24)} />
            </div>
            <div className="rc-finder-field" style={{ justifyContent: 'center' }}>
              <label>Auto-submit</label>
              <input type="checkbox" checked={schedAutoSubmit} onChange={e => setSchedAutoSubmit(e.target.checked)} style={{ width: 'auto' }} />
            </div>
            <button className="rc-finder-btn" onClick={handleSchedule} disabled={schedLoading || !schedSlice || !schedTime}>
              {schedLoading ? 'Scheduling...' : 'Schedule'}
            </button>
          </div>

          {/* Reservation list */}
          {reservations.length > 0 && (
            <div className="rc-finder-results" style={{ marginTop: 8 }}>
              <h4>Reservations</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {reservations.map(r => (
                  <div key={r.id} className="rc-alternative-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontWeight: 600 }}>{r.slice_name}</span>
                    <span style={{ color: 'var(--fabric-text-muted)', fontSize: 10 }}>
                      {formatDateTime(r.scheduled_time)}
                    </span>
                    <span className={`rc-available-badge ${r.status === 'pending' ? 'soon' : r.status === 'active' ? '' : 'unavailable'}`}>
                      {r.status}
                    </span>
                    {r.error && <span style={{ color: '#e25241', fontSize: 10 }}>{r.error}</span>}
                    {r.status === 'pending' && (
                      <button
                        style={{ fontSize: 10, padding: '1px 6px', cursor: 'pointer', border: '1px solid var(--fabric-border)', borderRadius: 3, background: 'transparent', color: 'var(--fabric-text)' }}
                        onClick={() => handleCancelReservation(r.id)}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="rc-toolbar">
        <button onClick={loadCalendar} disabled={calLoading}>
          {calLoading ? 'Loading...' : '\u21BB Refresh'}
        </button>
        {calLoading && <span className="rc-loading">Loading calendar...</span>}
        {calError && <span className="rc-loading" style={{ color: '#e25241' }}>{calError}</span>}
        <span className="rc-loading">{numDays > 0 ? `${numDays} days` : ''}</span>
      </div>

      {/* Timeline */}
      {!calendarData && calLoading ? (
        <div className="rc-empty">Loading resource calendar...</div>
      ) : sortedSites.length === 0 && !calLoading ? (
        <div className="rc-empty">No site data available</div>
      ) : (
        <div className="rc-timeline" ref={timelineRef}>
          <div
            className="rc-timeline-grid"
            style={{
              gridTemplateColumns: `140px repeat(${numDays}, 1fr)`,
              gridTemplateRows: `auto repeat(${sortedSites.length}, minmax(28px, auto))`,
            }}
          >
            {/* Header row */}
            <div className="rc-corner" />
            {days.map((d, i) => (
              <div key={i} className="rc-day-label">{formatDay(d)}</div>
            ))}

            {/* Site rows */}
            {sortedSites.map((site) => (
              <React.Fragment key={site.name}>
                {/* Label */}
                <div className="rc-site-label">
                  <span>{site.name}</span>
                  <div className="rc-util-bar">
                    <div
                      className="rc-util-fill"
                      style={{ width: site.cores_capacity > 0 ? `${((site.cores_capacity - site.cores_available) / site.cores_capacity) * 100}%` : '0%' }}
                      title={`${site.cores_available}/${site.cores_capacity} cores free`}
                    />
                  </div>
                </div>

                {/* Day cells with slice bars */}
                {days.map((_, di) => (
                  <div key={di} className="rc-day-cell" />
                ))}

                {/* Overlay bar layer spanning all day columns for this site row */}
              </React.Fragment>
            ))}
          </div>

          {/* Absolute-positioned bar overlay on top of the grid */}
          <BarOverlay
            sites={sortedSites}
            days={days}
            rangeStart={rangeStart}
            rangeDuration={rangeDuration}
            now={now}
            barStyle={barStyle}
            barClass={barClass}
            barTooltipText={barTooltipText}
            tooltip={tooltip}
            setTooltip={setTooltip}
            showNowLine={showNowLine}
            nowLeft={nowLeft}
            timelineRef={timelineRef}
          />
        </div>
      )}

      {/* Tooltip */}
      {tooltip && (
        <div className="rc-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}>
          {tooltip.text}
        </div>
      )}
    </div>
  );
}

/* --- Bar overlay: positions bars absolutely over the CSS grid --- */
interface BarOverlayProps {
  sites: CalendarSite[];
  days: Date[];
  rangeStart: number;
  rangeDuration: number;
  now: number;
  barStyle: (slice: CalendarSlice) => { left: string; width: string } | null;
  barClass: (slice: CalendarSlice) => string;
  barTooltipText: (slice: CalendarSlice) => string;
  tooltip: { x: number; y: number; text: string } | null;
  setTooltip: (t: { x: number; y: number; text: string } | null) => void;
  showNowLine: boolean;
  nowLeft: number;
  timelineRef: React.RefObject<HTMLDivElement | null>;
}

function BarOverlay({
  sites, days, rangeStart, rangeDuration, now,
  barStyle, barClass, barTooltipText,
  setTooltip, showNowLine, nowLeft, timelineRef,
}: BarOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState<{ headerH: number; labelW: number; rowH: number; totalW: number } | null>(null);

  // Measure grid dimensions after render
  useEffect(() => {
    const el = timelineRef.current;
    if (!el) return;
    const grid = el.querySelector('.rc-timeline-grid') as HTMLElement | null;
    if (!grid) return;

    const measure = () => {
      const corner = grid.querySelector('.rc-corner') as HTMLElement;
      const firstLabel = grid.querySelector('.rc-site-label') as HTMLElement;
      if (!corner || !firstLabel) return;
      const headerH = corner.offsetHeight;
      const labelW = firstLabel.offsetWidth;
      const rowH = firstLabel.offsetHeight;
      const totalW = grid.scrollWidth;
      setDims({ headerH, labelW, rowH, totalW });
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(grid);
    return () => ro.disconnect();
  }, [timelineRef, sites.length, days.length]);

  if (!dims || !rangeDuration) return null;

  const timelineWidth = dims.totalW - dims.labelW;

  return (
    <div
      ref={overlayRef}
      style={{
        position: 'absolute',
        top: 0,
        left: dims.labelW,
        width: timelineWidth,
        height: dims.headerH + sites.length * dims.rowH,
        pointerEvents: 'none',
      }}
    >
      {/* Now line */}
      {showNowLine && (
        <div
          className="rc-now-line"
          style={{ left: `${nowLeft}%`, top: dims.headerH }}
        />
      )}

      {/* Bars per site */}
      {sites.map((site, si) => {
        const topOffset = dims.headerH + si * dims.rowH;
        return site.slices.map((slice) => {
          const style = barStyle(slice);
          if (!style) return null;
          return (
            <div
              key={`${site.name}-${slice.id}`}
              className={barClass(slice)}
              style={{
                ...style,
                top: topOffset + 3,
                height: dims.rowH - 6,
                pointerEvents: 'auto',
              }}
              onMouseEnter={(e) => setTooltip({ x: e.clientX, y: e.clientY, text: barTooltipText(slice) })}
              onMouseMove={(e) => setTooltip({ x: e.clientX, y: e.clientY, text: barTooltipText(slice) })}
              onMouseLeave={() => setTooltip(null)}
            />
          );
        });
      })}
    </div>
  );
}
