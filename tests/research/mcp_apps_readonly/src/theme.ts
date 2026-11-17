/** Respect the host theme; defer to system preference when host gives no hint. */
export function applyHostTheme(root: HTMLElement, theme: string | undefined): void {
  if (theme === "dark" || theme === "light") {
    root.setAttribute("data-theme", theme);
  } else {
    root.removeAttribute("data-theme");
  }
}
