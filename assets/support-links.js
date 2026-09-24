(() => {
  const GITHUB_SPONSORS = "https://github.com/sponsors/oaslananka";
  const BUY_ME_A_COFFEE = "https://www.buymeacoffee.com/oaslananka";

  function supportLink({ href, label, className, icon }) {
    const anchor = document.createElement("a");
    anchor.className = `kmcp-support-link ${className}`;
    anchor.href = href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.setAttribute("aria-label", label);
    anchor.title = label;
    anchor.innerHTML = `${icon}<span>${label}</span>`;
    return anchor;
  }

  function mountSupportLinks() {
    const header = document.querySelector(".md-header__inner");
    if (!header || header.querySelector(".kmcp-support-links")) return;

    const nav = document.createElement("nav");
    nav.className = "kmcp-support-links";
    nav.setAttribute("aria-label", "Project support");
    nav.append(
      supportLink({
        href: GITHUB_SPONSORS,
        label: "GitHub Sponsors",
        className: "kmcp-support-link--github",
        icon: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 21s-7-4.35-9.33-8.37C.55 9.02 2.15 4.5 6.4 4.08c2.1-.2 4.03.77 5.1 2.32 1.07-1.55 3-2.52 5.1-2.32 4.25.42 5.85 4.94 3.73 8.55C19 15.01 16.02 17.58 12 21Z"/></svg>',
      }),
      supportLink({
        href: BUY_ME_A_COFFEE,
        label: "Buy me a coffee",
        className: "kmcp-support-link--coffee",
        icon: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 5h13v8a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6V5Zm13 2h1.5a3.5 3.5 0 1 1 0 7H17v-2h1.5a1.5 1.5 0 1 0 0-3H17V7ZM6 3h9v2H6V3Z"/></svg>',
      }),
    );

    const palette = header.querySelector('[data-md-component="palette"]');
    const search = header.querySelector('[data-md-component="search"]');
    header.insertBefore(nav, palette || search || null);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountSupportLinks, { once: true });
  } else {
    mountSupportLinks();
  }

  if (typeof document$ !== "undefined") {
    document$.subscribe(mountSupportLinks);
  }
})();
