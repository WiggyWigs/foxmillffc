// Head-to-Head page: two manager pickers. The comparison itself is built
// by h2hComparisonHtml() in h2h-table.js, which the Current Season page's
// Prime Time Matchup section uses too.

let statsData = null;

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    statsData = await res.json();
  } catch (err) {
    document.getElementById("h2h-output").innerHTML =
      `<p class="load-state">Couldn't load stats.json (${err.message}).</p>`;
    return;
  }

  const managers = Object.keys(statsData.h2h_summary || {}).sort();
  const selA = document.getElementById("mgrA");
  const selB = document.getElementById("mgrB");
  managers.forEach((m) => {
    selA.innerHTML += `<option value="${m}">${m}</option>`;
    selB.innerHTML += `<option value="${m}">${m}</option>`;
  });

  selA.addEventListener("change", renderComparison);
  selB.addEventListener("change", renderComparison);
});

function renderComparison() {
  const output = document.getElementById("h2h-output");
  const nameA = document.getElementById("mgrA").value;
  const nameB = document.getElementById("mgrB").value;

  if (!nameA || !nameB) {
    output.innerHTML = "";
    return;
  }
  if (nameA === nameB) {
    output.innerHTML = `<p class="load-state">Pick two different managers.</p>`;
    return;
  }

  output.innerHTML = h2hComparisonHtml(statsData, nameA, nameB);
}
