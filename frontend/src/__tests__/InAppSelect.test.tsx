import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import InAppSelect from '../components/InAppSelect';

function ControlledSelect({ onChange = vi.fn() }: { onChange?: (value: string) => void }) {
  const [value, setValue] = useState('alpha');

  return (
    <InAppSelect
      aria-label="Example select"
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        onChange(event.target.value);
      }}
    >
      <option value="alpha">Alpha</option>
      <option value="beta">Beta</option>
      <option value="gamma">Gamma</option>
    </InAppSelect>
  );
}

describe('InAppSelect', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'requestAnimationFrame', {
      configurable: true,
      value: (callback: FrameRequestCallback) => window.setTimeout(() => callback(performance.now()), 0),
    });
  });

  it('opens a DOM-rendered menu and selects an option without a native popup', async () => {
    const handleChange = vi.fn();
    render(<ControlledSelect onChange={handleChange} />);

    fireEvent.click(screen.getByRole('button', { name: 'Example select' }));

    const listbox = screen.getByRole('listbox');
    expect(listbox).toBeInTheDocument();
    expect(within(listbox).getAllByRole('option').map((option) => option.textContent)).toEqual(['Alpha', 'Beta', 'Gamma']);

    fireEvent.click(within(listbox).getByRole('option', { name: 'Beta' }));

    expect(handleChange).toHaveBeenCalledWith('beta');
    expect(screen.getByRole('button', { name: 'Example select' })).toHaveTextContent('Beta');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('filters in the open selector without letting text-entry keys trigger selection', () => {
    const handleChange = vi.fn();
    render(<ControlledSelect onChange={handleChange} />);

    fireEvent.click(screen.getByRole('button', { name: 'Example select' }));
    const filter = screen.getByPlaceholderText('Alpha');

    fireEvent.keyDown(filter, { key: ' ' });
    fireEvent.change(filter, { target: { value: 'ga' } });

    expect(handleChange).not.toHaveBeenCalled();
    expect(within(screen.getByRole('listbox')).getAllByRole('option').map((option) => option.textContent)).toEqual(['Gamma']);
  });
});
