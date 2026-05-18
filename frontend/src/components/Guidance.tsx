import { CircleHelp } from 'lucide-react';
import type { ReactNode } from 'react';

export const beginnerTourSteps = [
  {
    id: 'mission',
    title: 'Choose a mission',
    body: 'Start by picking the survey archive. TESS is the easiest first pass for the sample target.',
  },
  {
    id: 'search',
    title: 'Search a target',
    body: 'Type a TIC ID, Kepler name, TOI, or common alias, then run Search to load matches.',
  },
  {
    id: 'target',
    title: 'Pick the match',
    body: 'Select the target that best matches your search. OrbitLab then loads observation files for it.',
  },
  {
    id: 'product',
    title: 'Select an observation file',
    body: 'Choose a target pixel file. This is the data product used for previews and analysis.',
  },
  {
    id: 'run',
    title: 'Preview or analyze',
    body: 'Beginners can preview candidates first, then run the full analysis once the product looks useful.',
  },
  {
    id: 'plots',
    title: 'Read the plots',
    body: 'Use the orbit view, periodogram, folded curve, validation, physics, and ML panels to inspect each candidate.',
  },
] as const;

export type TourStepId = (typeof beginnerTourSteps)[number]['id'];
export type TourStep = (typeof beginnerTourSteps)[number];

export function HelpTip({ label }: { label: string }) {
  return (
    <span className="help-tip" aria-label="Help" title={label}>
      <CircleHelp size={13} />
    </span>
  );
}

export function BeginnerEmptyGuide({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="beginner-empty-guide">
      <strong>{title}</strong>
      <span>{children}</span>
    </div>
  );
}

export function TourOverlay({
  step,
  stepIndex,
  stepCount,
  onBack,
  onNext,
  onFinish,
}: {
  step: TourStep;
  stepIndex: number;
  stepCount: number;
  onBack: () => void;
  onNext: () => void;
  onFinish: () => void;
}) {
  const isFirstStep = stepIndex === 0;
  const isLastStep = stepIndex === stepCount - 1;

  return (
    <div className="tour-layer" role="dialog" aria-modal="false" aria-labelledby="tour-title">
      <div className="tour-card">
        <span className="tour-count">
          {stepIndex + 1} of {stepCount}
        </span>
        <h2 id="tour-title">{step.title}</h2>
        <p>{step.body}</p>
        <div className="tour-actions">
          <button type="button" onClick={onBack} disabled={isFirstStep}>
            Back
          </button>
          <button type="button" className="quiet-action" onClick={onFinish}>
            Skip
          </button>
          {isLastStep ? (
            <button type="button" onClick={onFinish}>
              Done
            </button>
          ) : (
            <button type="button" onClick={onNext}>
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
