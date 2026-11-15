/* GuiPAM — glue HTMX / Basecoat / thème. Aucun framework, aucun CDN. */

/* Thème clair/sombre */
document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-theme-toggle]");
  if (!toggle) return;
  const root = document.documentElement;
  const dark = root.classList.toggle("dark");
  root.dataset.theme = dark ? "dark" : "light"; // guitestyle suit data-theme, Basecoat la classe
  localStorage.setItem("guipam-theme", dark ? "dark" : "light");
});

/* Formulaire refusé (422) : on garde la modale et tout ce qui a été saisi. Seul le
   bloc d'erreurs est remplacé, et les champs fautifs passent en rouge. */
function showFormErrors(event) {
  const target = event.detail.target;
  const current = target.querySelector && target.querySelector("[data-form-errors]");
  if (target.id !== "modal" || !current) return false;
  const doc = new DOMParser().parseFromString(event.detail.xhr.responseText, "text/html");
  const incoming = doc.querySelector("[data-form-errors]");
  if (!incoming) return false;
  current.replaceWith(document.importNode(incoming, true));
  target.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
  const source = event.detail.requestConfig && event.detail.requestConfig.elt;
  const form = (source && source.closest && source.closest("form")) || target;
  const fields = (incoming.dataset.errorFields || "").split(" ").filter(Boolean);
  let first = null;
  fields.forEach((name) => {
    const field = form.querySelector('[name="' + name + '"]');
    if (!field) return;
    field.setAttribute("aria-invalid", "true");
    first = first || field;
  });
  if (first) first.focus();
  else target.querySelector("[data-form-errors]").scrollIntoView({ block: "nearest" });
  return true;
}

document.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.xhr.status !== 422) return;
  event.detail.isError = false;
  // Repli : re-rendu complet du partial (contrat d'origine) si le bloc est introuvable.
  event.detail.shouldSwap = !showFormErrors(event);
});

/* Un champ corrigé n'est plus signalé en rouge. */
document.addEventListener("input", (event) => {
  if (event.target.getAttribute && event.target.getAttribute("aria-invalid")) {
    event.target.removeAttribute("aria-invalid");
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
    // Champ pré-rempli à compléter (ex. début d'adresse IP) : curseur après le préfixe.
    const prefilled = dialog.querySelector("[data-caret-end]");
    if (prefilled) {
      prefilled.focus();
      prefilled.setSelectionRange(prefilled.value.length, prefilled.value.length);
    }
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
