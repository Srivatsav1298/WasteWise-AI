/* WasteWiseAI application shell: routing, loading, publish status.
 *
 * Plain scripts, no build step. The dashboard is a static reader of the
 * artefacts published by the warehouse.
 */
(function (global) {
  "use strict";

  var data = global.WW.data;
  var format = data.format;
  var el = data.el;

  var ROUTES = [
    { id: "overview", label: "Overview" },
    { id: "waste-risk", label: "Waste risk" },
    { id: "demand-events", label: "Demand & events" },
    { id: "simulator", label: "What-if" },
    { id: "trust", label: "Data trust" },
    { id: "lineage", label: "Pipeline" }
  ];

  var state = { bundle: null, route: "overview", gateOpen: false };

  // Routes that show measured numbers. When the gate is closed these render a
  // block notice instead of last run's numbers; the trust and pipeline pages
  // stay available because they are what explains the block.
  var DATA_ROUTES = ["overview", "waste-risk", "demand-events", "simulator"];

  function routeFromHash() {
    var hash = (global.location.hash || "").replace(/^#\/?/, "").split("?")[0];
    var match = ROUTES.filter(function (route) {
      return route.id === hash;
    })[0];
    return match ? match.id : "overview";
  }

  function markActiveNav(route) {
    var links = document.querySelectorAll(".nav-item");
    Array.prototype.forEach.call(links, function (link) {
      if (link.getAttribute("data-route") === route) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  function renderPublishBadge(status, report) {
    var host = document.getElementById("publish-badge");
    if (!host) {
      return;
    }
    host.innerHTML = "";
    var dot = el("span", { class: "dot", "aria-hidden": "true" });
    var text = el("span", { class: "masthead-status-text" });
    if (!status) {
      dot.classList.add("dot-wait");
      text.textContent = "Trust status unavailable";
    } else if (status.status === "published") {
      dot.classList.add("dot-ok");
      var summary = report && report.summary;
      text.textContent = summary
        ? "Published · " + summary.checks_passed + "/" + summary.checks_total + " expectations passed"
        : "Published";
    } else {
      dot.classList.add("dot-bad");
      text.textContent = "Publication blocked";
    }
    host.appendChild(dot);
    host.appendChild(text);
  }

  function renderFooter() {
    var host = document.getElementById("footer-run");
    if (!host || !state.bundle) {
      return;
    }
    var run = state.bundle.run_metadata || {};
    var report = state.bundle.trust_report || {};
    host.textContent =
      "run " +
      (run.run_id || "—") +
      " · contract " +
      (run.contract_version || "—") +
      " · trust report " +
      (report.generated_at ? format.date(report.generated_at) : "—");
  }

  function renderBlockedNotice(bundle) {
    var status = bundle.publish_status || {};
    var report = bundle.trust_report || {};
    var blockers = status.blockers || [];
    var summary = report.summary || {};

    var items = blockers.map(function (blocker) {
      return el("li", {}, [
        el("strong", { class: "mono", text: blocker.check_id }),
        document.createTextNode(": " + blocker.message),
        blocker.remediation
          ? el("div", { class: "card-note", text: "Fix: " + blocker.remediation })
          : null
      ]);
    });

    return el("div", { class: "stack" }, [
      el("div", { class: "page-head" }, [
        el("div", { class: "eyebrow", text: "Publication gate" }),
        el("h1", { text: "Publication blocked" }),
        el("p", {
          text:
            "The trust engine refused this run, so no number is published. " +
            "The dashboard is not showing last run's figures as if they were current."
        })
      ]),
      el("div", { class: "banner banner-bad", role: "status" }, [
        el("div", {}, [
          el("h2", {
            text:
              blockers.length +
              " blocking " +
              (blockers.length === 1 ? "expectation failed" : "expectations failed")
          }),
          el("p", {
            text:
              (summary.checks_passed || 0) +
              " of " +
              (summary.checks_total || "?") +
              " expectations passed. The run was stopped before anything was published."
          })
        ])
      ]),
      el("section", { class: "card" }, [
        el("div", { class: "card-head" }, [
          el("h2", { text: "Why the run was stopped" }),
          el("span", { class: "card-note", text: "blocking expectations" })
        ]),
        el("div", {}, [
          items.length
            ? el("ul", { class: "stack-tight" }, items)
            : el("p", { text: "No blocker detail was published with this run." }),
          el("p", { class: "card-note" }, [
            document.createTextNode("The trust console explains every failed expectation: "),
            el("a", { href: "#/trust", text: "open the data trust console" })
          ])
        ])
      ])
    ]);
  }

  function renderRoute() {
    var host = document.getElementById("view");
    if (!host) {
      return;
    }
    markActiveNav(state.route);
    document.title = "WasteWiseAI · " + (ROUTES.filter(function (route) {
      return route.id === state.route;
    })[0] || { label: "" }).label;

    if (!state.gateOpen && DATA_ROUTES.indexOf(state.route) !== -1) {
      host.innerHTML = "";
      host.appendChild(renderBlockedNotice(state.bundle || {}));
      return;
    }

    var view = global.WW.views[state.route];
    if (!view) {
      host.innerHTML = "";
      host.appendChild(el("div", { class: "error-box", text: "Unknown view: " + state.route }));
      return;
    }
    host.innerHTML = "";
    host.appendChild(view(state.bundle));
  }

  function boot() {
    var host = document.getElementById("view");
    host.innerHTML = "";
    host.appendChild(el("p", { class: "loading", text: "Loading published data…" }));

    data
      .loadAll()
      .then(function (bundle) {
        state.bundle = bundle;
        state.route = routeFromHash();
        state.gateOpen = Boolean(
          bundle.publish_status && bundle.publish_status.status === "published"
        );
        renderPublishBadge(bundle.publish_status, bundle.trust_report);
        renderFooter();
        renderRoute();
      })
      .catch(function (error) {
        host.innerHTML = "";
        host.appendChild(
          el("div", { class: "error-box" }, [
            el("strong", { text: "Could not load the published data. " }),
            document.createTextNode(
              "Run the pipeline (make pipeline) to publish the artefacts this page reads: " +
                error.message
            )
          ])
        );
      });
  }

  global.addEventListener("hashchange", function () {
    var next = routeFromHash();
    if (next !== state.route) {
      state.route = next;
      renderRoute();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  global.WW.app = { state: state, render: renderRoute, routes: ROUTES };
})(window);
