// Shared site nav — every page fetches nav.html and injects it into
// #nav-placeholder, instead of duplicating the same markup (and the
// hamburger toggle script) in every single HTML file. Update nav.html
// once, every page picks it up automatically.

document.addEventListener("DOMContentLoaded", async () => {
  const placeholder = document.getElementById("nav-placeholder");
  if (!placeholder) return;

  try {
    const res = await fetch("nav.html");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    placeholder.innerHTML = await res.text();
  } catch (err) {
    console.error("Couldn't load nav.html:", err.message);
    return;
  }

  // Mark the current page's link active by comparing against the
  // actual filename in the URL, rather than hardcoding it per page.
  const currentFile = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("#site-nav-links a").forEach((link) => {
    if (link.getAttribute("href") === currentFile) {
      link.classList.add("active");
    }
  });

  // Mobile hamburger menu — same mechanics used across every page.
  const navToggle = document.getElementById("nav-toggle");
  const navLinks = document.getElementById("site-nav-links");
  navToggle.addEventListener("click", () => {
    const isOpen = navLinks.classList.toggle("open");
    navToggle.classList.toggle("open", isOpen);
    navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });
  navToggle.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      navToggle.click();
    }
  });
  navLinks.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      navLinks.classList.remove("open");
      navToggle.classList.remove("open");
      navToggle.setAttribute("aria-expanded", "false");
    });
  });
});
