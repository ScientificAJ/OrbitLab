import { beforeEach, expect, it, vi } from 'vitest';

const rootMocks = vi.hoisted(() => ({
  createRoot: vi.fn(),
  render: vi.fn(),
}));

vi.mock('react-dom/client', () => ({
  default: { createRoot: rootMocks.createRoot },
}));

vi.mock('./App', () => ({
  default: () => <div>OrbitLab app</div>,
}));

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  rootMocks.createRoot.mockReturnValue({ render: rootMocks.render });
});

it('boots OrbitLab into the root element', async () => {
  await import('./main');

  expect(rootMocks.createRoot).toHaveBeenCalledWith(document.getElementById('root'));
  expect(rootMocks.render).toHaveBeenCalledOnce();
});
