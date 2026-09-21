(() => {
  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-app-nav]");
  if (toggle && nav) {
    document.body.classList.add("nav-ready");
    const setOpen = (open) => {
      toggle.setAttribute("aria-expanded", String(open));
      document.body.classList.toggle("nav-open", open);
    };
    toggle.addEventListener("click", () => {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        toggle.focus();
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
      empty("analysis", "Waiting for an effect");
    }
  });

  document.addEventListener("click", (event) => {
    const choice = event.target.closest(".choice-list button");
    if (!choice) return;
    choice.parentElement.querySelectorAll("button").forEach((button) => {
      button.removeAttribute("data-selected");
    });
    choice.setAttribute("data-selected", "");
  });

  document.addEventListener("visibilitychange", () => {
    document.querySelectorAll(".effect-layer, .aura").forEach((layer) => {
      layer.style.animationPlayState = document.hidden ? "paused" : "running";
    });
  });
})();
