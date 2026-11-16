import { parseReviewFixture, type ReviewFixture, type Severity } from "./review-schema.js";

function element<K extends keyof HTMLElementTagNameMap>(
  doc: Document,
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderReview(data: unknown, root: HTMLElement): void {
  const doc = root.ownerDocument;
  root.replaceChildren();
  let review: ReviewFixture;
  try {
    review = parseReviewFixture(data);
  } catch {
    const state = element(doc, "section", "review-state");
    state.setAttribute("role", "status");
    state.append(
      element(doc, "h2", "review-state-title", "Review unavailable"),
      element(doc, "p", "review-state-text", "This synthetic review result is missing or invalid. No project data was accessed."),
    );
    root.append(state);
    return;
  }

  const panel = element(doc, "section", "review-panel");
  panel.setAttribute("aria-label", "Synthetic KiCad design review");
  const header = element(doc, "header", "review-header");
  const eyebrow = element(doc, "p", "eyebrow", `${review.kind === "pcb" ? "PCB" : "Schematic"} / ${review.category} review`);
  const title = element(doc, "h1", "review-title", review.title);
  const disclaimer = element(doc, "p", "disclaimer", "Synthetic example — no live KiCad design analyzed");
  header.append(eyebrow, title, disclaimer);

  const summary = element(doc, "div", "review-summary");
  summary.setAttribute("aria-label", "Finding counts");
  for (const [kind, count] of [
    ["error", review.summary.errors],
    ["warning", review.summary.warnings],
  ] as const) {
    const card = element(doc, "div", `count count--${kind}`);
    card.append(
      element(doc, "span", "count-number", String(count)),
      element(doc, "span", "count-label", count === 1 ? kind : `${kind}s`),
    );
    summary.append(card);
  }

  const section = element(doc, "section", "findings-section");
  section.setAttribute("aria-label", "Review findings");
  const toolbar = element(doc, "div", "findings-toolbar");
  const label = element(doc, "h2", "findings-heading", "Findings");
  const filters = element(doc, "div", "filters");
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", "Filter findings by severity");
  const list = element(doc, "ul", "findings-list");
  const buttons: HTMLButtonElement[] = [];
  const options = [
    ["all", "All"],
    ["error", "Errors"],
    ["warning", "Warnings"],
  ] as const;

  const update = (filter: "all" | Severity) => {
    for (const button of buttons) {
      button.setAttribute("aria-pressed", String(button.dataset.filter === filter));
    }
    list.replaceChildren();
    const items = review.findings.filter((finding) => filter === "all" || finding.severity === filter);
    for (const finding of items) {
      const item = element(doc, "li", `finding finding--${finding.severity}`);
      item.setAttribute("data-finding", finding.code);
      item.append(
        element(doc, "span", "finding-level", finding.severity),
        element(doc, "strong", "finding-code", finding.code),
        element(doc, "p", "finding-message", finding.message),
      );
      list.append(item);
    }
    if (items.length === 0) {
      list.append(element(doc, "li", "no-findings", filter === "all" ? "No findings." : "No findings for this severity."));
    }
  };

  for (const [filter, name] of options) {
    const button = element(doc, "button", "filter", name);
    button.type = "button";
    button.dataset.filter = filter;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => update(filter));
    buttons.push(button);
    filters.append(button);
  }

  toolbar.append(label, filters);
  section.append(toolbar, list);
  panel.append(header, summary, section);
  root.append(panel);
  update("all");
}
