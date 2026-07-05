/* GuiPAM — glue HTMX / Basecoat / thème. Aucun framework, aucun CDN. */

/* Thème clair/sombre */
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-theme-toggle]");
  if (!toggle) return;
  const root = document.documentElement;
  const dark = root.classList.toggle("dark");
  localStorage.setItem("guipam-theme", dark ? "dark" : "light");
});

/* HTMX : accepter les swaps sur 422 (contrat des formulaires re-rendus avec erreurs). */
document.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.xhr.status === 422) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

/* Erreurs serveur (403 CSRF/lecture seule, 500…) → toast d'erreur. */
document.addEventListener("htmx:responseError", (event) => {
  const status = event.detail.xhr.status;
  if (status === 422) return;
  let message = "Erreur " + status;
  try {
    const body = JSON.parse(event.detail.xhr.responseText);
    if (body.detail) message = body.detail;
  } catch (_) { /* corps non JSON */ }
  document.dispatchEvent(new CustomEvent("basecoat:toast", {
    detail: { config: { category: "error", title: message, duration: 6000 } },
  }));
});

/* Toasts déclenchés côté serveur via HX-Trigger: {"toast": {...}} */
document.addEventListener("toast", (event) => {
  document.dispatchEvent(new CustomEvent("basecoat:toast", {
    detail: { config: Object.assign({ duration: 5000 }, event.detail) },
  }));
});

/* Modales : le partial chargé dans #modal contient un <dialog class="dialog">. */
document.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id !== "modal") return;
  const dialog = event.detail.target.querySelector("dialog");
  if (dialog && !dialog.open) {
    dialog.showModal();
    dialog.addEventListener("close", () => { event.detail.target.innerHTML = ""; }, { once: true });
  }
});

/* Confirmation stylée pour hx-confirm (au lieu de window.confirm). */
document.addEventListener("htmx:confirm", (event) => {
  if (!event.detail.question) return;
  event.preventDefault();
  const dialog = document.getElementById("confirm-dialog");
  dialog.querySelector("#confirm-message").textContent = event.detail.question;
  const ok = dialog.querySelector("[data-confirm-ok]");
  const cancel = dialog.querySelector("[data-confirm-cancel]");
  const done = (confirmed) => {
    dialog.close();
    ok.onclick = cancel.onclick = null;
    if (confirmed) event.detail.issueRequest(true);
  };
  ok.onclick = () => done(true);
  cancel.onclick = () => done(false);
  dialog.showModal();
});
