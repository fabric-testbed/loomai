import { render, screen, fireEvent } from '@testing-library/react';
import TestbedViewShell, { FABRIC_THEME, CHAMELEON_THEME } from '../components/TestbedViewShell';

describe('TestbedViewShell', () => {
  const tabs = [
    { id: 'a', label: 'Tab A' },
    { id: 'b', label: 'Tab B', badge: 5 },
  ];

  it('renders with FABRIC theme', () => {
    render(
      <TestbedViewShell theme={FABRIC_THEME} tabs={tabs} activeTab="a" onTabChange={() => {}}>
        Content
      </TestbedViewShell>,
    );
    expect(screen.getByText('FABRIC')).toBeInTheDocument();
    expect(screen.getByText('Tab A')).toBeInTheDocument();
    expect(screen.getByText('Tab B')).toBeInTheDocument();
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  it('renders with CHAMELEON theme', () => {
    render(
      <TestbedViewShell theme={CHAMELEON_THEME} tabs={tabs} activeTab="a" onTabChange={() => {}}>
        Content
      </TestbedViewShell>,
    );
    expect(screen.getByText('Chameleon')).toBeInTheDocument();
  });

  it('shows badge on tab', () => {
    render(
      <TestbedViewShell theme={FABRIC_THEME} tabs={tabs} activeTab="a" onTabChange={() => {}}>
        Content
      </TestbedViewShell>,
    );
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('does not show badge when value is 0', () => {
    const tabsNoBadge = [
      { id: 'a', label: 'Tab A' },
      { id: 'b', label: 'Tab B', badge: 0 },
    ];
    render(
      <TestbedViewShell theme={FABRIC_THEME} tabs={tabsNoBadge} activeTab="a" onTabChange={() => {}}>
        Content
      </TestbedViewShell>,
    );
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('calls onTabChange with correct id', () => {
    const onChange = vi.fn();
    render(
      <TestbedViewShell theme={FABRIC_THEME} tabs={tabs} activeTab="a" onTabChange={onChange}>
        Content
      </TestbedViewShell>,
    );
    fireEvent.click(screen.getByText('Tab B'));
    expect(onChange).toHaveBeenCalledWith('b');
  });

  it('renders toolbarContent when provided', () => {
    render(
      <TestbedViewShell
        theme={FABRIC_THEME}
        tabs={tabs}
        activeTab="a"
        onTabChange={() => {}}
        toolbarContent={<span>Toolbar Items</span>}
      >
        Content
      </TestbedViewShell>,
    );
    expect(screen.getByText('Toolbar Items')).toBeInTheDocument();
  });

  it('renders children in content area', () => {
    render(
      <TestbedViewShell theme={FABRIC_THEME} tabs={tabs} activeTab="a" onTabChange={() => {}}>
        <div data-testid="child">Hello</div>
      </TestbedViewShell>,
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });
});
