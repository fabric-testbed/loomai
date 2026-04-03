'use client';
import React, { useState, useEffect, useCallback } from 'react';
import * as api from '../api/client';
import type { SliceData, SiteInfo, ComponentModel } from '../types/fabric';
import EditorPanel from './EditorPanel';
import ChameleonEditor from './ChameleonEditor';

/**
 * CompositeEditorPanel — three-tab editor for composite meta-slices.
 *
 * Tab 1: Composite — member picker (add/remove FABRIC/Chameleon slices), status summary
 * Tab 2: FABRIC — embedded EditorPanel for a selected FABRIC member slice
 * Tab 3: Chameleon — embedded ChameleonEditor (formsOnly) for a selected Chameleon member slice
 */

interface CompositeEditorPanelProps {
  compositeSliceId: string;
  compositeSlice: any;
  fabricSlices: any[];
  chameleonSlices: any[];
  chameleonEnabled: boolean;
  chameleonSites?: any[];
  onMembersUpdated: (updated: any) => void;
  onCompositeGraphRefresh: () => void;
  onError: (msg: string) => void;
  onSwitchToSlice?: (testbed: 'fabric' | 'chameleon', sliceId: string) => void;
  onCreateSlice?: (testbed: 'fabric' | 'chameleon') => void;
  /** Callback when a FABRIC member slice is edited inline — passes updated SliceData */
  onFabricSliceUpdated?: (data: SliceData) => void;
  /** Current FABRIC sites, images, component models for the embedded editor */
  sites?: SiteInfo[];
  images?: string[];
  componentModels?: ComponentModel[];
  dark: boolean;
}

type CompositeTab = 'composite' | 'fabric' | 'chameleon';

export default React.memo(function CompositeEditorPanel({
  compositeSliceId,
  compositeSlice,
  fabricSlices,
  chameleonSlices,
  chameleonEnabled,
  onMembersUpdated,
  onCompositeGraphRefresh,
  onError,
  onSwitchToSlice,
  onCreateSlice,
  onFabricSliceUpdated,
  sites,
  images,
  componentModels,
  chameleonSites,
  dark,
}: CompositeEditorPanelProps) {
  const [tab, setTab] = useState<CompositeTab>('composite');
  const [saving, setSaving] = useState(false);

  // Selected member slice for inline editing
  const [selectedFabricMemberId, setSelectedFabricMemberId] = useState('');
  const [selectedChameleonMemberId, setSelectedChameleonMemberId] = useState('');
  const [fabricMemberData, setFabricMemberData] = useState<SliceData | null>(null);
  const [loadingMember, setLoadingMember] = useState(false);

  // Local member state for the picker
  const [localFabricMembers, setLocalFabricMembers] = useState<string[]>([]);
  const [localChameleonMembers, setLocalChameleonMembers] = useState<string[]>([]);

  // Sync from compositeSlice prop
  useEffect(() => {
    if (compositeSlice) {
      setLocalFabricMembers(compositeSlice.fabric_slices || []);
      setLocalChameleonMembers(compositeSlice.chameleon_slices || []);
    }
  }, [compositeSlice]);

  // Fetch FABRIC member slice data when selected for inline editing
  useEffect(() => {
    if (!selectedFabricMemberId) { setFabricMemberData(null); return; }
    setLoadingMember(true);
    api.getSlice(selectedFabricMemberId).then(data => {
      setFabricMemberData(data);
    }).catch(() => setFabricMemberData(null)).finally(() => setLoadingMember(false));
  }, [selectedFabricMemberId]);

  const saveMembership = useCallback(async (fabSlices: string[], chiSlices: string[]) => {
    if (!compositeSliceId) return;
    setSaving(true);
    try {
      const updated = await api.updateCompositeMembers(compositeSliceId, fabSlices, chiSlices);
      onMembersUpdated(updated);
      onCompositeGraphRefresh();
    } catch (e: any) {
      onError(e.message || 'Failed to update members');
    } finally {
      setSaving(false);
    }
  }, [compositeSliceId, onMembersUpdated, onCompositeGraphRefresh, onError]);

  const toggleFabricMember = useCallback((sliceId: string) => {
    const next = localFabricMembers.includes(sliceId)
      ? localFabricMembers.filter(id => id !== sliceId)
      : [...localFabricMembers, sliceId];
    setLocalFabricMembers(next);
    saveMembership(next, localChameleonMembers);
  }, [localFabricMembers, localChameleonMembers, saveMembership]);

  const toggleChameleonMember = useCallback((sliceId: string) => {
    const next = localChameleonMembers.includes(sliceId)
      ? localChameleonMembers.filter(id => id !== sliceId)
      : [...localChameleonMembers, sliceId];
    setLocalChameleonMembers(next);
    saveMembership(localFabricMembers, next);
  }, [localFabricMembers, localChameleonMembers, saveMembership]);

  if (!compositeSliceId || !compositeSlice) {
    return (
      <div style={{ padding: 16, textAlign: 'center', color: 'var(--fabric-text-muted)', fontSize: 12 }}>
        Select a composite slice to edit.
      </div>
    );
  }

  const memberFabricSummaries = compositeSlice.fabric_member_summaries || [];
  const memberChameleonSummaries = compositeSlice.chameleon_member_summaries || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Tab bar */}
      <div className="editor-top-tabs">
        <button className={tab === 'composite' ? 'active' : ''} onClick={() => setTab('composite')}>
          Composite
        </button>
        <button className={tab === 'fabric' ? 'active' : ''} onClick={() => setTab('fabric')}>
          FABRIC
        </button>
        {chameleonEnabled && (
          <button
            className={`${tab === 'chameleon' ? 'active chameleon-tab-active' : ''}`}
            onClick={() => setTab('chameleon')}
          >
            Chameleon
          </button>
        )}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        {tab === 'composite' && (
          <div>
            {/* Composite metadata */}
            <div style={{ marginBottom: 12, padding: '8px 4px', borderBottom: '1px solid var(--fabric-border)' }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{compositeSlice.name}</div>
              <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>
                State: <span style={{ fontWeight: 600, color: '#27aae1' }}>{compositeSlice.state || 'Draft'}</span>
                {' · '}{localFabricMembers.length} FABRIC + {localChameleonMembers.length} Chameleon
              </div>
            </div>

            {/* FABRIC slice picker */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#5798bc', marginBottom: 6 }}>
                FABRIC Slices
              </div>
              {fabricSlices.length === 0 ? (
                <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '4px 0' }}>No FABRIC slices available</div>
              ) : (
                fabricSlices.map(s => {
                  const isMember = localFabricMembers.includes(s.id);
                  return (
                    <label key={s.id} style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px',
                      cursor: 'pointer', fontSize: 12, opacity: saving ? 0.5 : 1,
                    }}>
                      <input
                        type="checkbox"
                        checked={isMember}
                        onChange={() => toggleFabricMember(s.id)}
                        disabled={saving}
                        style={{ accentColor: '#5798bc' }}
                      />
                      <span style={{ fontWeight: isMember ? 600 : 400 }}>{s.name}</span>
                      <span style={{
                        fontSize: 9, fontWeight: 600, textTransform: 'uppercase',
                        padding: '1px 4px', borderRadius: 3,
                        background: s.state === 'StableOK' ? 'rgba(0, 142, 122, 0.15)' : 'rgba(87, 152, 188, 0.15)',
                        color: s.state === 'StableOK' ? '#008e7a' : '#5798bc',
                      }}>
                        {s.state || 'Draft'}
                      </span>
                      {s.nodes && <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)' }}>{s.nodes.length} node{s.nodes.length !== 1 ? 's' : ''}</span>}
                    </label>
                  );
                })
              )}
            </div>

            {/* Chameleon slice picker */}
            {chameleonEnabled && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#39B54A', marginBottom: 6 }}>
                  Chameleon Slices
                </div>
                {chameleonSlices.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '4px 0' }}>No Chameleon slices available</div>
                ) : (
                  chameleonSlices.map(s => {
                    const isMember = localChameleonMembers.includes(s.id);
                    return (
                      <label key={s.id} style={{
                        display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px',
                        cursor: 'pointer', fontSize: 12, opacity: saving ? 0.5 : 1,
                      }}>
                        <input
                          type="checkbox"
                          checked={isMember}
                          onChange={() => toggleChameleonMember(s.id)}
                          disabled={saving}
                          style={{ accentColor: '#39B54A' }}
                        />
                        <span style={{ fontWeight: isMember ? 600 : 400 }}>{s.name}</span>
                        <span style={{
                          fontSize: 9, fontWeight: 600, textTransform: 'uppercase',
                          padding: '1px 4px', borderRadius: 3,
                          background: 'rgba(57, 181, 74, 0.15)', color: '#39B54A',
                        }}>
                          {s.state || 'Draft'}
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
            )}

            {/* Member summaries */}
            {(memberFabricSummaries.length > 0 || memberChameleonSummaries.length > 0) && (
              <div style={{ marginTop: 8, padding: '8px 4px', borderTop: '1px solid var(--fabric-border)' }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)', marginBottom: 6 }}>
                  Member Status
                </div>
                {memberFabricSummaries.map((m: any) => (
                  <div key={m.id} style={{ fontSize: 11, padding: '2px 0', display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: '#5798bc' }}>[FAB]</span>
                    <span style={{ fontWeight: 500 }}>{m.name}</span>
                    <span style={{ color: 'var(--fabric-text-muted)' }}>{m.state}</span>
                    <span style={{ color: 'var(--fabric-text-muted)' }}>{m.node_count} node{m.node_count !== 1 ? 's' : ''}</span>
                  </div>
                ))}
                {memberChameleonSummaries.map((m: any) => (
                  <div key={m.id} style={{ fontSize: 11, padding: '2px 0', display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: '#39B54A' }}>[CHI]</span>
                    <span style={{ fontWeight: 500 }}>{m.name}</span>
                    <span style={{ color: 'var(--fabric-text-muted)' }}>{m.state}</span>
                    {m.site && <span style={{ color: 'var(--fabric-text-muted)' }}>@ {m.site}</span>}
                  </div>
                ))}
              </div>
            )}

            {/* Cross-testbed connections */}
            {localFabricMembers.length > 0 && localChameleonMembers.length > 0 && (
              <div style={{ marginTop: 8, padding: '8px 4px', borderTop: '1px solid var(--fabric-border)' }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#27aae1', marginBottom: 6 }}>
                  Cross-Testbed Connections
                </div>
                {(compositeSlice.cross_connections || []).map((conn: any, i: number) => (
                  <div key={i} style={{ fontSize: 11, padding: '4px 0', display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ color: '#5798bc', fontWeight: 500 }}>{conn.fabric_node}</span>
                    <span style={{ color: 'var(--fabric-text-muted)' }}>{'\u2194'}</span>
                    <span style={{ color: '#39B54A', fontWeight: 500 }}>{conn.chameleon_node}</span>
                    <span style={{ fontSize: 9, color: '#27aae1', background: 'rgba(39,170,225,0.1)', padding: '1px 4px', borderRadius: 3 }}>
                      {conn.type === 'l2_stitch' ? 'L2 Stitch' : 'FABNetv4'}
                    </span>
                    <button
                      style={{ background: 'none', border: 'none', color: 'var(--fabric-text-muted)', cursor: 'pointer', fontSize: 12, padding: '0 2px' }}
                      onClick={async () => {
                        const updated = (compositeSlice.cross_connections || []).filter((_: any, j: number) => j !== i);
                        try {
                          await api.updateCompositeCrossConnections(compositeSliceId, updated);
                          onMembersUpdated({ ...compositeSlice, cross_connections: updated });
                          onCompositeGraphRefresh();
                        } catch (e: any) { onError(e.message); }
                      }}
                    >x</button>
                  </div>
                ))}
                <div style={{ marginTop: 6, fontSize: 10, color: 'var(--fabric-text-muted)' }}>
                  All member nodes on FABNetv4 are automatically connected via the shared FABRIC Internet.
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'fabric' && (
          <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Slice selector */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8, alignItems: 'center' }}>
              <select
                style={{ flex: 1, fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)' }}
                value={selectedFabricMemberId}
                onChange={(e) => setSelectedFabricMemberId(e.target.value)}
              >
                <option value="">-- Select FABRIC slice --</option>
                {memberFabricSummaries.map((m: any) => (
                  <option key={m.id} value={m.id}>{m.name} ({m.state})</option>
                ))}
              </select>
              {onCreateSlice && (
                <button
                  style={{ fontSize: 10, padding: '3px 8px', borderRadius: 3, border: '1px solid #5798bc', background: 'rgba(87,152,188,0.1)', color: '#5798bc', cursor: 'pointer', whiteSpace: 'nowrap' }}
                  onClick={() => onCreateSlice('fabric')}
                >+ New</button>
              )}
            </div>
            {/* Embedded editor or placeholder */}
            {selectedFabricMemberId && fabricMemberData ? (
              <div style={{ flex: 1, overflow: 'auto', border: '1px solid var(--fabric-border)', borderRadius: 4 }}>
                <EditorPanel
                  sliceData={fabricMemberData}
                  sliceName={fabricMemberData.name || selectedFabricMemberId}
                  onSliceUpdated={(data) => {
                    setFabricMemberData(data);
                    onFabricSliceUpdated?.(data);
                    onCompositeGraphRefresh();
                  }}
                  onCollapse={() => setSelectedFabricMemberId('')}
                  sites={sites || []}
                  images={images || []}
                  componentModels={componentModels || []}
                  viewContext="fabric"
                />
              </div>
            ) : selectedFabricMemberId && loadingMember ? (
              <div style={{ textAlign: 'center', padding: 20, color: 'var(--fabric-text-muted)' }}>Loading slice...</div>
            ) : localFabricMembers.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p>No FABRIC slices in this composite.</p>
                <p style={{ fontSize: 11 }}>Add existing slices in the Composite tab or create a new one above.</p>
              </div>
            ) : !selectedFabricMemberId ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p style={{ fontSize: 11 }}>Select a FABRIC slice above to edit it.</p>
              </div>
            ) : null}
          </div>
        )}

        {tab === 'chameleon' && chameleonEnabled && (
          <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Slice selector */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8, alignItems: 'center' }}>
              <select
                style={{ flex: 1, fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)' }}
                value={selectedChameleonMemberId}
                onChange={(e) => setSelectedChameleonMemberId(e.target.value)}
              >
                <option value="">-- Select Chameleon slice --</option>
                {memberChameleonSummaries.map((m: any) => (
                  <option key={m.id} value={m.id}>{m.name} ({m.state})</option>
                ))}
              </select>
              {onCreateSlice && (
                <button
                  style={{ fontSize: 10, padding: '3px 8px', borderRadius: 3, border: '1px solid #39B54A', background: 'rgba(57,181,74,0.1)', color: '#39B54A', cursor: 'pointer', whiteSpace: 'nowrap' }}
                  onClick={() => onCreateSlice('chameleon')}
                >+ New</button>
              )}
            </div>
            {/* Embedded Chameleon editor or placeholder */}
            {selectedChameleonMemberId ? (
              <div style={{ flex: 1, overflow: 'auto', border: '1px solid var(--fabric-border)', borderRadius: 4 }}>
                <ChameleonEditor
                  sites={chameleonSites || []}
                  onError={onError}
                  formsOnly
                  draftId={selectedChameleonMemberId}
                  onDraftUpdated={() => onCompositeGraphRefresh()}
                />
              </div>
            ) : localChameleonMembers.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p>No Chameleon slices in this composite.</p>
                <p style={{ fontSize: 11 }}>Add existing slices in the Composite tab or create a new one above.</p>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p style={{ fontSize: 11 }}>Select a Chameleon slice above to edit it.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
