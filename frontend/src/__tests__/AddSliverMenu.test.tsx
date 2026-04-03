import { render, screen, fireEvent } from '@testing-library/react';
import AddSliverMenu from '../components/editor/AddSliverMenu';

describe('AddSliverMenu', () => {
  it('shows all base non-chameleon options when menu opened', () => {
    render(<AddSliverMenu onSelect={() => {}} />);
    fireEvent.click(screen.getByTitle('Add a new sliver'));
    expect(screen.getByText('VM Node')).toBeInTheDocument();
    expect(screen.getByText('Network (L2)')).toBeInTheDocument();
    expect(screen.getByText('Network (L3)')).toBeInTheDocument();
    expect(screen.getByText('Facility Port')).toBeInTheDocument();
    expect(screen.getByText('Port Mirror')).toBeInTheDocument();
  });

  it('hides chameleon options when not enabled', () => {
    render(<AddSliverMenu onSelect={() => {}} />);
    fireEvent.click(screen.getByTitle('Add a new sliver'));
    expect(screen.queryByText('Chameleon Node')).not.toBeInTheDocument();
    expect(screen.queryByText('Chameleon Network')).not.toBeInTheDocument();
    expect(screen.queryByText('Floating IP')).not.toBeInTheDocument();
  });

  it('shows chameleon options when enabled', () => {
    render(<AddSliverMenu onSelect={() => {}} chameleonEnabled />);
    fireEvent.click(screen.getByTitle('Add a new sliver'));
    expect(screen.getByText('Chameleon Node')).toBeInTheDocument();
    expect(screen.getByText('Chameleon Network')).toBeInTheDocument();
    expect(screen.getByText('Floating IP')).toBeInTheDocument();
  });

  it('filters by visibleTypes', () => {
    render(<AddSliverMenu onSelect={() => {}} visibleTypes={['node', 'l2network']} />);
    fireEvent.click(screen.getByTitle('Add a new sliver'));
    expect(screen.getByText('VM Node')).toBeInTheDocument();
    expect(screen.getByText('Network (L2)')).toBeInTheDocument();
    expect(screen.queryByText('Network (L3)')).not.toBeInTheDocument();
    expect(screen.queryByText('Facility Port')).not.toBeInTheDocument();
    expect(screen.queryByText('Port Mirror')).not.toBeInTheDocument();
  });

  it('calls onSelect with correct type when option clicked', () => {
    const onSelect = vi.fn();
    render(<AddSliverMenu onSelect={onSelect} />);
    fireEvent.click(screen.getByTitle('Add a new sliver'));
    fireEvent.click(screen.getByText('VM Node'));
    expect(onSelect).toHaveBeenCalledWith('node');
  });

  it('closes menu after selection', () => {
    render(<AddSliverMenu onSelect={() => {}} />);
    fireEvent.click(screen.getByTitle('Add a new sliver'));
    expect(screen.getByText('VM Node')).toBeInTheDocument();
    fireEvent.click(screen.getByText('VM Node'));
    expect(screen.queryByText('Network (L2)')).not.toBeInTheDocument();
  });
});
