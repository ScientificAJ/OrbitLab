import { useCallback, useEffect, useRef, useState } from 'react';

export type ActiveModal = 'aperture' | 'bls' | 'models' | 'sessions' | null;

export function useModalState(isCloseBlocked: (modal: Exclude<ActiveModal, null>) => boolean = () => false) {
  const [activeModal, setActiveModal] = useState<ActiveModal>(null);
  const isCloseBlockedRef = useRef(isCloseBlocked);

  useEffect(() => {
    isCloseBlockedRef.current = isCloseBlocked;
  }, [isCloseBlocked]);

  function openModal(modal: Exclude<ActiveModal, null>) {
    setActiveModal(modal);
  }

  const closeActiveModal = useCallback(() => {
    setActiveModal((current) => {
      if (current && isCloseBlockedRef.current(current)) return current;
      return null;
    });
  }, []);

  useEffect(() => {
    if (!activeModal) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') closeActiveModal();
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeModal, closeActiveModal]);

  return {
    activeModal,
    openModal,
    closeActiveModal,
    setActiveModal,
  };
}
