import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mock react-plotly.js: it cannot render under jsdom (no WebGL/layout), so we
// substitute a div that records the props the component passes through.
const plotProps: Record<string, unknown>[] = [];
vi.mock('react-plotly.js', () => ({
  default: (props: Record<string, unknown>) => {
    plotProps.push(props);
    return <div data-testid="mock-plot" data-plot="true" />;
  },
}));

// Import after the mock is registered.
import { SciencePlot } from './SciencePlot';

describe('SciencePlot', () => {
  it('renders an empty placeholder when there is no data', () => {
    render(<SciencePlot title="Periodogram" x={[]} y={[]} xLabel="Period" yLabel="Power" testId="periodogram" />);
    const empty = screen.getByTestId('periodogram');
    expect(empty).toHaveClass('empty-plot');
    expect(empty).toHaveTextContent('Periodogram');
    expect(screen.queryByTestId('mock-plot')).not.toBeInTheDocument();
  });

  it('renders an empty placeholder when only y is empty', () => {
    render(<SciencePlot title="Folded" x={[1, 2]} y={[]} xLabel="Phase" yLabel="Flux" />);
    expect(screen.getByText('Folded')).toHaveClass('empty-plot');
  });

  it('renders the Plot frame with populated data and default line mode', () => {
    plotProps.length = 0;
    render(<SciencePlot title="Light curve" x={[0, 1, 2]} y={[1, 0.99, 1]} xLabel="Time" yLabel="Flux" testId="lc" />);
    const frame = screen.getByTestId('lc');
    expect(frame).toHaveClass('plot-frame');
    expect(screen.getByTestId('mock-plot')).toBeInTheDocument();

    const props = plotProps.at(-1)!;
    const data = props.data as Array<{ mode: string; x: number[]; y: number[] }>;
    expect(data[0].mode).toBe('lines');
    expect(data[0].x).toEqual([0, 1, 2]);
  });

  it('honors an explicit mode prop', () => {
    plotProps.length = 0;
    render(<SciencePlot title="Scatter" x={[1]} y={[2]} xLabel="X" yLabel="Y" mode="markers" />);
    const data = plotProps.at(-1)!.data as Array<{ mode: string }>;
    expect(data[0].mode).toBe('markers');
  });
});
