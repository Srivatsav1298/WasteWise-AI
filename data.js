/* WasteWiseAI data layer.
 *
 * The dashboard reads published artefacts only. It never queries the warehouse
 * and never recomputes a published metric: the Data Trust Engine has already
 * decided what may be shown and at which trust state.
 */
(function (global) {
  "use strict";

  var MART = "data/marts/";

  /* The artefacts this dashboard renders. The reader only fetches what a view
   * actually shows: the registry and the expectation list travel inside
   * trust_report.json, and the dimension tables are not rendered anywhere. */
  var FILES = [
    "overview",
    "waste_priority",
    "waste_by_reason",
    "waste_by_category",
    "demand_events",
    "purchase_plan",
    "publish_status",
    "trust_report",
    "lineage",
    "reconciliation",
    "run_metadata"
  ];

  var cache = {};

  function load(name) {
    if (cache[name]) {
      return cache[name];
    }
    cache[name] = fetch(MART + name + ".json", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error(name + ".json failed with HTTP " + response.status);
        }
        return response.json();
      })
      .catch(function (error) {
        delete cache[name];
        throw error;
      });
    return cache[name];
  }

  function loadAll() {
    return Promise.all(
      FILES.map(function (name) {
        return load(name).catch(function () {
          return null;
        });
      })
    ).then(function (results) {
      var bundle = {};
      FILES.forEach(function (name, index) {
        bundle[name] = results[index];
      });
      return bundle;
    });
  }

  /* ------------------------------------------------------------------ format */

  var numberFormat = new Intl.NumberFormat("en-GB");

  function number(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "—";
    }
    var parsed = Number(value);
    var fixed = digits === undefined ? parsed : parsed.toFixed(digits);
    return numberFormat.format(fixed);
  }

  function money(value) {
    if (value === null || value === undefined) {
      return "—";
    }
    return "NOK " + number(Math.round(value));
  }

  function percent(value, digits) {
    if (value === null || value === undefined) {
      return "—";
    }
    return number(Number(value) * 100, digits === undefined ? 1 : digits) + "%";
  }

  function lift(value) {
    if (value === null || value === undefined) {
      return "not measured";
    }
    var parsed = Number(value);
    var sign = parsed > 0 ? "+" : "";
    return sign + number(parsed, 1) + "%";
  }

  function date(value) {
    if (!value) {
      return "—";
    }
    var parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return String(value);
    }
    return parsed.toISOString().slice(0, 10);
  }

  function titleCase(value) {
    if (!value) {
      return "—";
    }
    return String(value)
      .replace(/_/g, " ")
      .replace(/\b\w/g, function (character) {
        return character.toUpperCase();
      });
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* -------------------------------------------------------------------- dom */

  function el(tag, attributes, children) {
    var node = document.createElement(tag);
    Object.keys(attributes || {}).forEach(function (key) {
      if (key === "class") {
        node.className = attributes[key];
      } else if (key === "html") {
        node.innerHTML = attributes[key];
      } else if (key === "text") {
        node.textContent = attributes[key];
      } else if (key.slice(0, 2) === "on" && typeof attributes[key] === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), attributes[key]);
      } else if (attributes[key] !== null && attributes[key] !== undefined) {
        node.setAttribute(key, attributes[key]);
      }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) {
        return;
      }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function trustChip(state, extra) {
    var label = state === "measured" ? "measured" : state === "partial" ? "partial" : "unverified";
    var className =
      state === "measured"
        ? "chip chip-measured"
        : state === "partial"
          ? "chip chip-partial"
          : "chip chip-unverified";
    var node = el("span", { class: className });
    node.appendChild(el("span", { class: "chip-dot", "aria-hidden": "true" }));
    node.appendChild(document.createTextNode(label + (extra ? " · " + extra : "")));
    return node;
  }

  global.WW = global.WW || {};
  global.WW.data = {
    load: load,
    loadAll: loadAll,
    files: FILES,
    format: {
      number: number,
      money: money,
      percent: percent,
      lift: lift,
      date: date,
      titleCase: titleCase,
      escapeHtml: escapeHtml
    },
    el: el,
    trustChip: trustChip
  };
})(window);
