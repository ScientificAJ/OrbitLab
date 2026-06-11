import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  BeginnerEmptyGuide,
  FirstRunWelcome,
  HelpTip,
  INSTALL_COMMAND,
  TourOverlay,
  beginnerTourSteps,
} from './Guidance';

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

describe('FirstRunWelcome', () => {
  it('renders the install command, payload list, and dismiss affordances', async () => {
    const onDismiss = vi.fn();
    render(<FirstRunWelcome onDismiss={onDismiss} />);

    expect(screen.getByRole('dialog', { name: 'Welcome aboard OrbitLab' })).toBeInTheDocument();
    expect(screen.getByText(INSTALL_COMMAND)).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'What the installer sets up' }).children).toHaveLength(6);

    await userEvent.click(screen.getByRole('button', { name: /Start exploring/ }));
    expect(onDismiss).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole('button', { name: 'Close welcome' }));
    expect(onDismiss).toHaveBeenCalledTimes(2);
  });

  it('stays on the Copy label when the clipboard write fails', async () => {
    const onDismiss = vi.fn();
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard blocked'));
    Object.defineProperty(window.navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<FirstRunWelcome onDismiss={onDismiss} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy install command' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(INSTALL_COMMAND));
    expect(screen.queryByText('Copied')).not.toBeInTheDocument();
    expect(screen.getByText('Copy')).toBeInTheDocument();
  });
});
