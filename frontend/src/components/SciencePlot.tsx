import Plot from 'react-plotly.js';

type Props = {
  title: string;
  x: number[];
  y: number[];
  xLabel: string;
  yLabel: string;
  mode?: 'lines' | 'markers' | 'lines+markers';
  testId?: string;
};

export function SciencePlot({ title, x, y, xLabel, yLabel, mode = 'lines', testId }: Props) {
  if (x.length === 0 || y.length === 0) {
    return (
      <div className="empty-plot" data-testid={testId}>
        {title}
      </div>
    );
  }
  return (
    <div data-testid={testId} className="plot-frame">
      <Plot
        data={[
          {
            x,
            y,
            type: 'scatter',
            mode,
            line: { color: 'var(--accent)', width: 1.4 },
            marker: { color: 'var(--accent)', size: 3 },
          },
        ]}
        layout={{
          title: { text: title, font: { color: 'var(--text-strong)', size: 13 } },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          margin: { l: 44, r: 16, t: 36, b: 36 },
          xaxis: {
            title: { text: xLabel },
            color: 'var(--muted)',
            gridcolor: 'var(--border)',
            zerolinecolor: 'var(--border-strong)',
          },
          yaxis: {
            title: { text: yLabel },
            color: 'var(--muted)',
            gridcolor: 'var(--border)',
            zerolinecolor: 'var(--border-strong)',
          },
          showlegend: false,
          autosize: true,
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        className="plot"
      />
    </div>
  );
}
