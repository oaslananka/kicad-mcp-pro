import { App, PostMessageTransport } from "@modelcontextprotocol/ext-apps";
import { renderReview } from "./view.js";
import { applyHostTheme } from "./theme.js";

const root = document.getElementById("review-root");
if (!root) throw new Error("Review root missing");

const app = new App({ name: "Synthetic KiCad Review", version: "0.0.0" }, {});
const setTheme = (theme: string | undefined) => applyHostTheme(document.documentElement, theme);

// Handlers must be registered before the UI handshake.
app.ontoolresult = (result) => {
  renderReview(result.isError ? null : (result.structuredContent ?? null), root);
};
app.onhostcontextchanged = (context) => setTheme(context.theme);

void app.connect(new PostMessageTransport(window.parent, window.parent))
  .then(() => setTheme(app.getHostContext()?.theme))
  .catch(() => renderReview(null, root));
