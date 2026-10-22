/* Script minimale per gesart - nessuna dipendenza esterna (funziona offline). */
(function () {
  "use strict";

  // --- Sincronizza l'URL con i filtri applicati (per link condivisibili) ---
  function serializzaFiltri(form) {
    const filtri = {};
    form.querySelectorAll("[name^='f__']").forEach(function (campo) {
      const parti = campo.name.split("__");
      if (parti.length !== 3) return;
      const colonna = parti[1];
      const aspetto = parti[2];
      if (!colonna || aspetto === "q") return;
      const valore = campo.value;
      if (valore === "") return;
      filtri[colonna] = filtri[colonna] || {};
      filtri[colonna][aspetto] = valore;
    });
    const ricerca = form.querySelector("[name='f__q__val']");
    if (ricerca && ricerca.value.trim() !== "") filtri.q = ricerca.value.trim();
    return filtri;
  }

  function aggiornaUrl(form) {
    const filtri = serializzaFiltri(form);
    const url = new URL(window.location.href);
    const json = JSON.stringify(filtri);
    if (Object.keys(filtri).length === 0) {
      url.searchParams.delete("flt");
    } else {
      url.searchParams.set("flt", json);
    }
    url.searchParams.set("pag", "1");
    window.history.replaceState({}, "", url.toString());
    const hidden = document.getElementById("flt-hidden");
    if (hidden) hidden.value = json;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("form-filtri");
    if (form) {
      form.addEventListener("change", function () {
        aggiornaUrl(form);
      });
      form.addEventListener("submit", function () {
        aggiornaUrl(form);
      });
    }
  });

  // --- Salvataggio di una vista (apre il dialogo e precompila i filtri) ---
  window.salvaVista = function () {
    const form = document.getElementById("form-filtri");
    const dialogo = document.getElementById("dialogo-vista");
    if (!dialogo) return;
    if (form) {
      aggiornaUrl(form);
      const json = JSON.stringify(serializzaFiltri(form));
      const hidden = document.getElementById("form-vista").querySelector("input[name='flt']");
      if (hidden) hidden.value = json;
    }
    dialogo.style.display = "block";
    const nome = document.getElementById("nome-vista");
    if (nome) nome.focus();
  };

  // --- Applicazione di una vista salvata ---
  window.applicaVista = function (vistaId) {
    if (!vistaId) return;
    window.location.href = "/viste/applica/" + vistaId;
  };
})();
