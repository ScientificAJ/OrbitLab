import Plot from 'react-plotly.js';

type Props = {
  title: string;
  x: number[];
  y: number[];
  xLabel: string;
  yLabel: string;
  mode?: 'lines' | 'markers' | 'lines+markers';
};

export function SciencePlot({ title, x, y, xLabel, yLabel, mode = 'lines' }: Props) {
  if (x.length === 0 || y.length === 0) {
    return <div className="empty-plot">{title}</div>;
  }
  return (
    <Plot
      data={[
        {
          x,
          y,
          type: 'scattergl',
          mode,
          line: { color: '#78dce8', width: 1.4 },
          marker: { color: '#78dce8', size: 3 }
        }
      ]}
      layout={{
        title: { text: title, font: { color: '#d8edf2', size: 13 } },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        margin: { l: 44, r: 16, t: 36, b: 36 },
        xaxis: { title: { text: xLabel }, color: '#8fb0b8', gridcolor: '#1b343d', zerolinecolor: '#31515b' },
        yaxis: { title: { text: yLabel }, color: '#8fb0b8', gridcolor: '#1b343d', zerolinecolor: '#31515b' },
        showlegend: false,
        autosize: true
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      className="plot"
    />
  );
}
