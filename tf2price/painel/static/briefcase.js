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

  document.addEventListener("visibilitychange", () => {
    document.querySelectorAll(".effect-layer, .aura").forEach((layer) => {
      layer.style.animationPlayState = document.hidden ? "paused" : "running";
    });
  });
})();
