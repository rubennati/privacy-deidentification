/** Smoothly scroll an element into view and briefly flash it via the shared CSS animation. */
export function scrollAndFlash(elementId: string): void {
  const target = document.getElementById(elementId);
  if (!target) {
    return;
  }
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.remove("pii-jump-flash");
  // Force a reflow so re-adding the class restarts the animation on repeated clicks.
  void target.offsetWidth;
  target.classList.add("pii-jump-flash");
}
