/**
 * Axiom Mobility (Fleetline) - Debounce & Throttle Utilities.
 *
 * Prevents UI input stampedes on OSM autocomplete, CRM searches, and bulk editing.
 */

export function debounce(fn, delayMs = 250) {
  let timer = null;
  const debounced = function (...args) {
    const context = this;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn.apply(context, args);
    }, delayMs);
  };

  debounced.cancel = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  return debounced;
}

export function throttle(fn, intervalMs = 200) {
  let lastTime = 0;
  let timer = null;

  return function (...args) {
    const context = this;
    const now = Date.now();

    if (now - lastTime >= intervalMs) {
      lastTime = now;
      fn.apply(context, args);
    } else if (!timer) {
      timer = setTimeout(() => {
        lastTime = Date.now();
        timer = null;
        fn.apply(context, args);
      }, intervalMs - (now - lastTime));
    }
  };
}
