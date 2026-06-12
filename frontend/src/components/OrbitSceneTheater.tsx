import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

type Props = {
  children: React.ReactNode;
  onExit: () => void;
};

/**
 * Fullscreen "theater mode" shell for OrbitScene. Renders into a body portal
 * so the simulation escapes the panel layout entirely; the scene component
 * itself stays mounted, preserving simulation state across the transition.
 */
export function OrbitSceneTheater({ children, onExit }: Props) {
  const exitButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onExit();
    };
    window.addEventListener('keydown', onKey);

    // [CREATIVE: lock body scroll while in theater so wheel-zoom gestures
    // never scroll the page behind the simulation]
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // [CREATIVE: move focus to the exit button on entry and hand it back on
    // exit, so keyboard users are never stranded behind the portal]
    const previousFocus = document.activeElement as HTMLElement | null;
    exitButtonRef.current?.focus();

    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus?.();
    };
  }, [onExit]);

  return createPortal(
    <>
      <div className="orbit-theater-backdrop" />
      <div className="orbit-theater-container" role="dialog" aria-modal="true" aria-label="Orbit theater mode" data-testid="orbit-theater">
        <button
          type="button"
          ref={exitButtonRef}
          className="orbit-theater-exit"
          onClick={onExit}
          aria-label="Exit theater mode"
          data-testid="orbit-theater-exit"
        >
          ✕ Exit<kbd>ESC</kbd>
        </button>
        {children}
      </div>
    </>,
    document.body,
  );
}
