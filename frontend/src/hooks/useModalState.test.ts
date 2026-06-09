import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useModalState } from './useModalState';

describe('useModalState', () => {
  it('starts with no active modal', () => {
    const { result } = renderHook(() => useModalState());
    expect(result.current.activeModal).toBeNull();
  });

  it('opens and closes a modal', () => {
    const { result } = renderHook(() => useModalState());

    act(() => result.current.openModal('settings'));
    expect(result.current.activeModal).toBe('settings');

    act(() => result.current.closeActiveModal());
    expect(result.current.activeModal).toBeNull();
  });

  it('keeps the modal open when closing is blocked', () => {
    const isBlocked = vi.fn().mockReturnValue(true);
    const { result } = renderHook(() => useModalState(isBlocked));

    act(() => result.current.openModal('aperture'));
    act(() => result.current.closeActiveModal());

    expect(isBlocked).toHaveBeenCalledWith('aperture');
    expect(result.current.activeModal).toBe('aperture');
  });

  it('closes on Escape keypress and ignores other keys', () => {
    const { result } = renderHook(() => useModalState());

    act(() => result.current.openModal('models'));
    expect(result.current.activeModal).toBe('models');

    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' })));
    expect(result.current.activeModal).toBe('models');

    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
    expect(result.current.activeModal).toBeNull();
  });

  it('does not listen for Escape when no modal is open (early return)', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    renderHook(() => useModalState());
    // No modal open at mount: the keydown effect should bail before binding.
    expect(addSpy.mock.calls.some(([type]) => type === 'keydown')).toBe(false);
    addSpy.mockRestore();
  });

  it('removes the keydown listener on cleanup when the modal changes', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const { result } = renderHook(() => useModalState());

    act(() => result.current.openModal('tour'));
    act(() => result.current.setActiveModal(null));

    expect(removeSpy.mock.calls.some(([type]) => type === 'keydown')).toBe(true);
    removeSpy.mockRestore();
  });

  it('picks up an updated isCloseBlocked callback via the effect', () => {
    let blocked = false;
    const { result, rerender } = renderHook(() => useModalState(() => blocked));

    act(() => result.current.openModal('bls'));
    blocked = true;
    rerender();
    act(() => result.current.closeActiveModal());
    expect(result.current.activeModal).toBe('bls');

    blocked = false;
    rerender();
    act(() => result.current.closeActiveModal());
    expect(result.current.activeModal).toBeNull();
  });

  it('uses the default no-op blocker when none is provided', () => {
    const { result } = renderHook(() => useModalState());
    act(() => result.current.openModal('voyager'));
    act(() => result.current.closeActiveModal());
    expect(result.current.activeModal).toBeNull();
  });
});
