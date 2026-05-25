
(function () {
  const ready = (fn) => {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  };

  ready(() => {

    const categorySelect = document.getElementById("category-select");
    const questionPacks = document.querySelectorAll(".question-pack");
    const syncQuestionPacks = () => {
      if (!categorySelect || !questionPacks.length) return;
      const selectedOption = categorySelect.options[categorySelect.selectedIndex];
      const selectedName = selectedOption ? selectedOption.getAttribute("data-name") : "";
      questionPacks.forEach((pack) => {
        const active = pack.getAttribute("data-category") === selectedName;
        pack.style.display = active ? "grid" : "none";
        pack.querySelectorAll("input, textarea, select").forEach((field) => {
          field.disabled = !active;
        });
      });
    };
    if (categorySelect && questionPacks.length) {
      categorySelect.addEventListener("change", syncQuestionPacks);
      syncQuestionPacks();
    }


    document.body.classList.add("loaded");

    const nav = document.getElementById("nav");
    const header = document.querySelector(".header");
    const progress = document.getElementById("scroll-progress");

    document.addEventListener("click", (event) => {
      const menuButton = event.target.closest("[data-menu]");
      if (menuButton && nav) nav.classList.toggle("open");

      const navLink = event.target.closest(".nav a");
      if (navLink && nav && nav.classList.contains("open")) nav.classList.remove("open");

      const showPassword = event.target.closest("[data-show-password]");
      if (showPassword) {
        event.preventDefault();
        const wrapper = showPassword.closest(".password-field") || showPassword.parentElement;
        const input = wrapper ? wrapper.querySelector("input") : null;
        if (!input) return;
        const hidden = input.getAttribute("type") === "password";
        input.setAttribute("type", hidden ? "text" : "password");
        showPassword.textContent = hidden ? "Скрыть" : "Показать";
        input.focus();
      }

      const helpOpen = event.target.closest("[data-help-open]");
      if (helpOpen) {
        event.preventDefault();
        const modal = document.getElementById("help-modal");
        if (modal) {
          modal.classList.add("open");
          modal.setAttribute("aria-hidden", "false");
        }
      }

      const helpClose = event.target.closest("[data-help-close]");
      if (helpClose) {
        const modal = document.getElementById("help-modal");
        if (modal) {
          modal.classList.remove("open");
          modal.setAttribute("aria-hidden", "true");
        }
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        const modal = document.getElementById("help-modal");
        if (modal) {
          modal.classList.remove("open");
          modal.setAttribute("aria-hidden", "true");
        }
      }
    });

    const setScrollState = () => {
      const top = window.scrollY || document.documentElement.scrollTop || 0;
      if (header) header.classList.toggle("scrolled", top > 12);

      if (progress) {
        const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
        const percent = scrollHeight > 0 ? (top / scrollHeight) * 100 : 0;
        progress.style.width = Math.min(100, Math.max(0, percent)) + "%";
      }
    };

    window.addEventListener("scroll", setScrollState, { passive: true });
    setScrollState();

    const currentPath = window.location.pathname;
    document.querySelectorAll("[data-nav]").forEach((link) => {
      try {
        const path = new URL(link.href).pathname;
        if (path !== "/" && currentPath.indexOf(path) === 0) link.classList.add("active");
      } catch (e) {}
    });

    const revealItems = document.querySelectorAll(".reveal, .service-card, .master-card, .panel, .metric, .contact-card, .safety-card, .testimonial, .process-step");
    revealItems.forEach((el) => {
      if (!el.classList.contains("reveal")) el.classList.add("reveal");
    });

    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.1, rootMargin: "0px 0px -35px 0px" });

      revealItems.forEach((el, index) => {
        el.style.animationDelay = Math.min(index * 0.025, 0.25) + "s";
        observer.observe(el);
      });
    } else {
      revealItems.forEach((el) => el.classList.add("visible"));
    }

    const animateCounter = (counter) => {
      const target = Number(counter.getAttribute("data-count") || "0");
      const suffix = counter.getAttribute("data-suffix") || "";
      const duration = 900;
      const start = performance.now();

      const tick = (now) => {
        const p = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        counter.textContent = Math.round(target * eased) + suffix;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    const counters = document.querySelectorAll("[data-count]");
    if ("IntersectionObserver" in window) {
      const counterObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animateCounter(entry.target);
            counterObserver.unobserve(entry.target);
          }
        });
      }, { threshold: 0.4 });
      counters.forEach((counter) => counterObserver.observe(counter));
    } else {
      counters.forEach(animateCounter);
    }

    document.querySelectorAll("input, textarea, select").forEach((field) => {
      const validate = () => {
        if (!field.required && !field.value) return;
        if (field.checkValidity()) {
          field.classList.add("is-valid");
          field.classList.remove("is-invalid");
        } else if (field.value || document.activeElement === field) {
          field.classList.add("is-invalid");
          field.classList.remove("is-valid");
        }
      };
      field.addEventListener("input", validate);
      field.addEventListener("blur", validate);
    });

    const password = document.querySelector("[data-password]");
    const bar = document.querySelector("[data-password-bar]");
    const hint = document.querySelector("[data-password-hint]");
    const meter = bar ? bar.closest(".password-meter") : null;

    const scorePassword = (value) => {
      let score = 0;
      if (value.length >= 8) score += 1;
      if (/[0-9]/.test(value)) score += 1;
      if (/[a-zA-Zа-яА-Я]/.test(value)) score += 1;
      if (/[^0-9a-zA-Zа-яА-Я]/.test(value)) score += 1;
      if (["password", "qwerty", "12345678", "homehero", "admin123", "demo123"].includes(value.toLowerCase())) score = 0;
      return score;
    };

    if (password && bar && meter && hint) {
      password.addEventListener("input", () => {
        const value = password.value;
        const score = scorePassword(value);
        meter.classList.remove("good", "strong");

        if (!value) {
          bar.style.width = "0";
          hint.textContent = "Добавьте буквы, цифры и минимум 8 символов.";
          return;
        }

        if (score <= 1) {
          bar.style.width = "33%";
          hint.textContent = "Слишком лёгкий пароль. Нужны минимум 8 символов, буквы и цифры.";
        } else if (score <= 3) {
          meter.classList.add("good");
          bar.style.width = "66%";
          hint.textContent = "Нормально, но можно добавить спецсимвол для усиления.";
        } else {
          meter.classList.add("strong");
          bar.style.width = "100%";
          hint.textContent = "Сильный пароль.";
        }
      });
    }

    document.querySelectorAll(".btn-danger").forEach((button) => {
      button.addEventListener("click", (event) => {
        const text = button.textContent.trim().toLowerCase();
        if (text.includes("отмен") || text.includes("закрыть") || text.includes("блок")) {
          if (!confirm("Подтвердить действие?")) event.preventDefault();
        }
      });
    });

    setTimeout(() => {
      document.querySelectorAll(".flash").forEach((el) => {
        el.style.opacity = "0";
        el.style.transform = "translateY(-10px)";
        setTimeout(() => el.remove(), 400);
      });
    }, 4500);
  });
})();
