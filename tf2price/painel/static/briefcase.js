(() => {
  document.addEventListener("submit", (event) => {
    const message = event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-app-nav]");
  if (toggle && nav) {
    document.body.classList.add("nav-ready");
    const setOpen = (open, restoreFocus = false) => {
      toggle.setAttribute("aria-expanded", String(open));
      document.body.classList.toggle("nav-open", open);
      if (!open && restoreFocus) toggle.focus();
    };
    toggle.addEventListener("click", () => {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false, true);
      }
    });
    nav.addEventListener("click", (event) => {
      if (event.target.closest("a") && window.matchMedia("(max-width: 48rem)").matches) {
        setOpen(false);
      }
    });
  }

  const empty = (id, message) => {
    const target = document.getElementById(id);
    if (target) target.innerHTML = `<p class="empty-state">${message}</p>`;
  };

  document.addEventListener("htmx:beforeRequest", (event) => {
    const level = event.detail.elt.dataset.caseRequest;
    if (level === "search") {
      empty("effects", "Waiting for an item");
      empty("analysis", "Waiting for an effect");
    } else if (level === "item") {
      empty("effects", "Loading effects");
      empty("analysis", "Waiting for an effect");
    } else if (level === "effect") {
      empty("analysis", "Loading evidence");
    }
  });

  document.addEventListener("click", (event) => {
    const choice = event.target.closest(".choice-list button");
    if (!choice) return;
    const isEffect = choice.dataset.caseRequest === "effect";
    choice.parentElement.querySelectorAll("button").forEach((button) => {
      button.removeAttribute("data-selected");
      button.classList.remove("is-selected");
      if (isEffect && button.dataset.caseRequest === "effect") {
        button.setAttribute("aria-pressed", "false");
      }
    });
    choice.setAttribute("data-selected", "");
    if (isEffect) choice.setAttribute("aria-pressed", "true");
  });

  const syncVisibility = () => {
    document.body.classList.toggle("page-hidden", document.hidden);
  };
  document.addEventListener("visibilitychange", syncVisibility);
  syncVisibility();
})();
