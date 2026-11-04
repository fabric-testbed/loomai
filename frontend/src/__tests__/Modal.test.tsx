import { render, screen, fireEvent } from '@testing-library/react';
import { Modal } from '../components/Modal';

describe('Modal', () => {
  it('portals to document.body with the mandated inline positioning', () => {
    const { container } = render(
      <div data-testid="host">
        <Modal overlayClassName="toolbar-modal-overlay" className="toolbar-modal" data-testid="m">
          <h4>Hi</h4>
        </Modal>
      </div>,
    );
    const overlay = screen.getByTestId('m');
    // Rendered under body, not inside the host subtree.
    expect(container.querySelector('[data-testid="m"]')).toBeNull();
    expect(overlay.parentElement).toBe(document.body);
    expect(overlay).toHaveClass('toolbar-modal-overlay');
    expect(overlay.style.position).toBe('fixed');
    expect(overlay.style.zIndex).toBe('99999');
    expect(overlay.style.display).toBe('flex');
    expect(overlay.style.alignItems).toBe('center');
    expect(overlay.style.justifyContent).toBe('center');

    const box = screen.getByRole('dialog');
    expect(box).toHaveClass('toolbar-modal');
    expect(box.getAttribute('aria-modal')).toBe('true');
    expect(box.style.maxHeight).toBe('80vh');
    expect(box.style.overflowY).toBe('auto');
    expect(document.activeElement).toBe(box);
  });

  it('closes on Escape and backdrop click, not on clicks inside', () => {
    const onClose = vi.fn();
    render(
      <Modal onClose={onClose} data-testid="m">
        <button>inside</button>
      </Modal>,
    );
    fireEvent.click(screen.getByText('inside'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('m'));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('is not dismissable without onClose', () => {
    render(<Modal data-testid="m"><p>working…</p></Modal>);
    fireEvent.click(screen.getByTestId('m'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByText('working…')).toBeInTheDocument();
  });
});
