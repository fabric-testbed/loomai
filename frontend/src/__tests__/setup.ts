import '@testing-library/jest-dom';

// Mock next/dynamic — returns a stub component so imports don't fail
vi.mock('next/dynamic', () => ({
  __esModule: true,
  default: (_fn: () => Promise<unknown>) => {
    const Component = () => null;
    Component.displayName = 'DynamicComponent';
    return Component;
  },
}));
