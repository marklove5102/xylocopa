import { useRef, useCallback } from "react";

/**
 * Hook for detecting long-press gestures on both touch and mouse.
 * Returns event handlers to spread onto the target element.
 *
 * @param {Function} onLongPress - called when press exceeds `delay` ms
 * @param {Function} onTap       - called on a normal short tap
 * @param {number}   delay       - long-press threshold in ms (default 500)
 */
export default function useLongPress(onLongPress, onTap, delay = 500) {
  const timerRef = useRef(null);
  const firedRef = useRef(false);
  const movedRef = useRef(false);
  const startPos = useRef(null);

  const clear = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const onPointerDown = useCallback(
    (e) => {
      firedRef.current = false;
      movedRef.current = false;
      startPos.current = { x: e.clientX, y: e.clientY };
      clear();
      timerRef.current = setTimeout(() => {
        firedRef.current = true;
        timerRef.current = null;
        onLongPress?.(e);
      }, delay);
    },
    [onLongPress, delay, clear],
  );

  const onPointerUp = useCallback(
    (e) => {
      clear();
      // Skip tap if the pointer moved past the slop threshold — that was a
      // scroll/swipe, not a tap. Without this, vertical list scrolling on
      // touch devices fires tap on release and opens the wrong page.
      if (!firedRef.current && !movedRef.current) {
        onTap?.(e);
      }
    },
    [onTap, clear],
  );

  const onPointerMove = useCallback(
    (e) => {
      if (!startPos.current) return;
      const dx = e.clientX - startPos.current.x;
      const dy = e.clientY - startPos.current.y;
      // 12px slop — generous enough for finger jitter, tight enough that a
      // deliberate tap stays a tap.
      if (dx * dx + dy * dy > 144) {
        movedRef.current = true;
        clear();
      }
    },
    [clear],
  );

  const onPointerLeave = useCallback(() => clear(), [clear]);
  const onPointerCancel = useCallback(() => clear(), [clear]);

  // Prevent context menu on long-press (mobile)
  const onContextMenu = useCallback((e) => e.preventDefault(), []);

  return {
    onPointerDown,
    onPointerUp,
    onPointerMove,
    onPointerLeave,
    onPointerCancel,
    onContextMenu,
  };
}
