// Populates the manager dropdown from the real roster, then on submit
// opens a pre-filled GitHub issue (labeled "lore-submission") in a new
// tab. Nothing here writes to the repo directly — that would require
// exposing a write-capable GitHub token in client-side code, which
// anyone could steal from the page's source. The actual write happens
// safely server-side, via a GitHub Action that watches for issues with
// this label and processes them automatically (see
// .github/workflows/process_lore_submission.yml).

const REPO = "WiggyWigs/foxmillffc";

document.addEventListener("DOMContentLoaded", async () => {
  const select = document.getElementById("lore-manager");
  try {
    const res = await fetch("data/manager_roster.json");
    const data = await res.json();
    const managers = [...data.managers].sort();
    managers.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load manager roster:", err);
    const opt = document.createElement("option");
    opt.textContent = "Couldn't load manager list — refresh and try again";
    opt.disabled = true;
    select.appendChild(opt);
  }

  document.getElementById("lore-form").addEventListener("submit", (e) => {
    e.preventDefault();

    const manager = select.value;
    const loreText = document.getElementById("lore-text").value.trim();
    if (!manager || !loreText) return;

    const title = `Lore submission: ${manager}`;
    const body = `Manager: ${manager}\n\n${loreText}`;
    const url = `https://github.com/${REPO}/issues/new?` +
      `title=${encodeURIComponent(title)}` +
      `&body=${encodeURIComponent(body)}` +
      `&labels=${encodeURIComponent("lore-submission")}`;

    window.open(url, "_blank");

    const status = document.getElementById("input-status");
    status.textContent = "A GitHub tab just opened — sign in if needed, then click \"Submit new issue\" there to finish. It'll show up in that manager's lore automatically once submitted.";
    status.style.display = "block";

    document.getElementById("lore-form").reset();
  });
});
