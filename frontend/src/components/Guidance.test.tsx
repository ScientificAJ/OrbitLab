import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BeginnerEmptyGuide, HelpTip, TourOverlay, beginnerTourSteps } from './Guidance';

describe('HelpTip', () => {
  it('renders an accessible help marker with the label as title', () => {
    render(<HelpTip label="What is a TIC ID?" />);
    const tip = screen.getByLabelText('Help');
    expect(tip).toHaveAttribute('title', 'What is a TIC ID?');
  });
});

describe('BeginnerEmptyGuide', () => {
  it('renders the title and children', () => {
    render(
      <BeginnerEmptyGuide title="No candidates yet">
        <span>Run a preview to begin.</span>
      </BeginnerEmptyGuide>,
    );
    expect(screen.getByText('No candidates yet')).toBeInTheDocument();
    expect(screen.getByText('Run a preview to begin.')).toBeInTheDocument();
  });
});

describe('TourOverlay', () => {
  const steps = beginnerTourSteps;

  it('shows Next (not Done) and disables Back on the first step', async () => {
    const onBack = vi.fn();
    const onNext = vi.fn();
    const onFinish = vi.fn();
    render(
      <TourOverlay
        step={steps[0]}
        stepIndex={0}
        stepCount={steps.length}
        onBack={onBack}
        onNext={onNext}
        onFinish={onFinish}
      />,
    );

    expect(screen.getByText(`1 of ${steps.length}`)).toBeInTheDocument();
    expect(screen.getByText(steps[0].title)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();

    const next = screen.getByRole('button', { name: 'Next' });
    await userEvent.click(next);
    expect(onNext).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: 'Done' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onFinish).toHaveBeenCalledOnce();
  });

  it('shows Done (not Next) and enables Back on a middle/last step', async () => {
    const onBack = vi.fn();
    const onNext = vi.fn();
    const onFinish = vi.fn();
    const lastIndex = steps.length - 1;
    render(
      <TourOverlay
        step={steps[lastIndex]}
        stepIndex={lastIndex}
        stepCount={steps.length}
        onBack={onBack}
        onNext={onNext}
        onFinish={onFinish}
      />,
    );

    const back = screen.getByRole('button', { name: 'Back' });
    expect(back).toBeEnabled();
    await userEvent.click(back);
    expect(onBack).toHaveBeenCalledOnce();

    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
    const done = screen.getByRole('button', { name: 'Done' });
    await userEvent.click(done);
    expect(onFinish).toHaveBeenCalledOnce();
  });

  it('exposes six beginner tour steps with stable ids', () => {
    expect(beginnerTourSteps.map((s) => s.id)).toEqual(['mission', 'search', 'target', 'product', 'run', 'plots']);
  });
});
