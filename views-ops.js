/* WasteWiseAI operations views: what-if simulator, data trust console, pipeline.
 *
 * The simulator is a scenario tool, not a forecast. It applies a user chosen
 * reduction to published waste cost and states plainly that the result is a
 * scenario estimate, never a published metric.
 */
(function (global) {
  "use strict";

  var data = global.WW.data;
  var charts = global.WW.charts;
  var format = data.format;
  var el = data.el;
  var table = global.WW.views.table;
  var card = global.WW.views.card;

  /* ------------------------------------------------------------ simulator */

  function simulator(bundle) {
    var byReason = bundle.waste_by_reason || [];
    var metrics = (bundle.trust_report && bundle.trust_report.metrics) || [];
    var wasteCostMetric = metrics.find(function (metric) {
      return metric.metric_key === "waste_cost_at_risk";
    });

    var head = el("div", { class: "page-head" }, [
      el("div", { class: "eyebrow", text: "What-if" }),
      el("h1", { text: "What would a prevention lever be worth?" }),
      el("p", {
        text:
          "Move a lever and see the cost it removes. The result is a scenario estimate " +
          "computed from published waste cost. It is not a published metric and it is not a forecast."
      })
    ]);

    var state = { reason: byReason.length ? byReason[0].waste_reason : "spoilage", reduction: 20 };

    var resultHost = el("div", { class: "grid grid-3" });
    var scopeHost = el("div", {});

    function currentRow() {
      return byReason.find(function (row) {
        return row.waste_reason === state.reason;
      });
    }

    function renderScope() {
      scopeHost.innerHTML = "";
      scopeHost.appendChild(
        charts.barChart({
          rows: byReason.map(function (row) {
            return {
              label: format.titleCase(row.waste_reason),
              value: row.total_cost,
              display: format.money(row.total_cost),
              color: row.waste_reason === state.reason ? charts.palette[0] : "#c9c2b2"
            };
          }),
          ariaLabel: "Waste cost by reason with the selected reason highlighted"
        })
      );
    }

    function renderResult() {
      var row = currentRow();
      resultHost.innerHTML = "";
      renderScope();
      if (!row) {
        return;
      }
      var avoided = (row.total_cost * state.reduction) / 100;
      var remaining = row.total_cost - avoided;
      resultHost.appendChild(
        el("section", { class: "card stat" }, [
          el("div", { class: "stat-label", text: "Cost in scope" }),
          el("div", { class: "stat-value" }, [document.createTextNode(format.money(row.total_cost))]),
          el("div", {
            class: "stat-meta",
            text:
              format.titleCase(row.waste_reason) +
              " · " +
              format.number(row.waste_event_count) +
              " waste events"
          })
        ])
      );
      resultHost.appendChild(
        el("section", { class: "card stat" }, [
          el("div", { class: "stat-label", text: "Avoided by the lever" }),
          el("div", { class: "stat-value" }, [document.createTextNode(format.money(avoided))]),
          el("div", { class: "stat-meta", text: state.reduction + "% reduction on this reason" })
        ])
      );
      resultHost.appendChild(
        el("section", { class: "card stat" }, [
          el("div", { class: "stat-label", text: "Still at risk" }),
          el("div", { class: "stat-value" }, [document.createTextNode(format.money(remaining))]),
          el("div", { class: "stat-meta", text: "after the scenario reduction" })
        ])
      );
    }

    var reasonSelect = el(
      "select",
      {
        id: "sim-reason",
        onchange: function (event) {
          state.reason = event.target.value;
          renderResult();
        }
      },
      byReason.map(function (row) {
        return el("option", { value: row.waste_reason, text: format.titleCase(row.waste_reason) });
      })
    );

    var slider = el("input", {
      type: "range",
      id: "sim-reduction",
      min: "0",
      max: "100",
      step: "5",
      value: String(state.reduction),
      oninput: function (event) {
        state.reduction = Number(event.target.value);
        reductionLabel.textContent = state.reduction + "%";
        renderResult();
      }
    });
    var reductionLabel = el("span", { class: "mono", text: state.reduction + "%" });

    var leverCard = card(
      "Prevention lever",
      "Published policy per reason",
      table(
        [
          { label: "Reason", render: function (row) { return format.titleCase(row.waste_reason); } },
          { label: "Avoidability", render: function (row) { return format.titleCase(row.avoidability); } },
          { label: "Lever", render: function (row) { return row.prevention_lever; } },
          { label: "Cost", numeric: true, render: function (row) { return format.money(row.total_cost); } }
        ],
        byReason,
        { label: "Prevention lever by reason" }
      )
    );

    var scopeCard = card(
      "Cost in scope by reason",
      "Selected reason highlighted",
      scopeHost
    );

    var scenarioCard = card(
      "Scenario",
      "Not a published metric",
      el("div", { class: "stack" }, [
        el("div", { class: "filters" }, [
          el("div", { class: "field" }, [el("label", { for: "sim-reason", text: "Waste reason" }), reasonSelect]),
          el("div", { class: "field" }, [
            el("label", { for: "sim-reduction", text: "Reduction applied" }),
            el("div", { class: "row" }, [slider, reductionLabel])
          ])
        ]),
        resultHost,
        el("p", { class: "card-note" }, [
          document.createTextNode(
            "Scenario estimate. Built from " +
              (wasteCostMetric ? wasteCostMetric.metric_name : "published waste cost") +
              ", trust state " +
              (wasteCostMetric ? wasteCostMetric.trust_state : "unknown") +
              ". No forecast is implied."
          )
        ])
      ])
    );

    renderResult();

    return el("div", { class: "stack" }, [head, scenarioCard, el("div", { class: "grid grid-2" }, [scopeCard, leverCard])]);
  }

  /* ---------------------------------------------------------- trust console */

  function trustConsole(bundle) {
    var report = bundle.trust_report || {};
    var status = bundle.publish_status || {};
    var metrics = report.metrics || [];
    var checks = report.checks || [];
    var sources = report.sources || [];

    var head = el("div", { class: "page-head" }, [
      el("div", { class: "eyebrow", text: "Data trust console" }),
      el("h1", { text: "What the pipeline knows, and what it refuses to claim" }),
      el("p", {
        text:
          "The trust engine evaluates declared expectations after every build, assigns a " +
          "trust state to every metric, and blocks publication when a blocking expectation breaks."
      })
    ]);

    var hasStatus = Boolean(status && status.status);
    var isPublished = status.status === "published";
    var summary = report.summary || { checks_passed: 0, checks_total: "?" };
    var bannerClass = isPublished ? "banner banner-ok" : "banner banner-bad";
    var banner = el("div", { class: bannerClass, role: "status" }, [
      el("div", {}, [
        el("h2", {
          text: !hasStatus
            ? "Trust status unavailable"
            : isPublished
              ? "Publication gate open: " + summary.checks_passed + " of " + summary.checks_total + " expectations passed"
              : "Publication blocked: " + (status.blockers || []).length + " blocking expectations failed"
        }),
        el("p", {
          text: !hasStatus
            ? "No trust report has been published. Run make pipeline to build the warehouse and evaluate its expectations."
            : isPublished
              ? "Generated " + format.date(status.generated_at) + ". No blocking failure, so every metric below may be shown."
              : (status.blockers || [])
                  .map(function (blocker) {
                    return blocker.check_id + ": " + blocker.message;
                  })
                  .join(" ") || "The gate is closed. See the expectations below."
        })
      ])
    ]);

    var metricRows = metrics.map(function (metric) {
      return {
        metric_key: metric.metric_key,
        metric_name: metric.metric_name,
        source_model: metric.source_model,
        measurement_type: metric.measurement_type,
        unit: metric.unit,
        owner: metric.owner,
        definition: metric.definition,
        caveat: metric.caveat,
        trust_state: metric.trust_state,
        displayable: metric.displayable,
        protected: metric.protected !== false,
        lineage: metric.lineage
      };
    });

    var metricCard = card(
      "Metric registry",
      "Every published number, with its definition and trust state",
      table(
        [
          { label: "Metric", render: function (row) { return row.metric_name; } },
          { label: "Type", render: function (row) { return format.titleCase(row.measurement_type); } },
          { label: "Model", render: function (row) { return row.source_model; } },
          { label: "Owner", render: function (row) { return row.owner; } },
          { label: "Protected", render: function (row) {
              return el("span", {
                class: row.protected ? "chip chip-measured" : "chip chip-unverified",
                text: row.protected ? "checked" : "uncovered"
              });
            } },
          { label: "Trust state", render: function (row) { return data.trustChip(row.trust_state); } },
          { label: "Shown", render: function (row) { return row.displayable ? "yes" : "no"; } },
          { label: "Caveat", render: function (row) { return row.caveat; } }
        ],
        metricRows,
        { scroll: true, label: "Metric registry" }
      )
    );

    var checkCard = card(
      "Expectations",
      "Declared, versioned with the models they protect",
      table(
        [
          { label: "Check", render: function (row) { return row.check_id; } },
          { label: "Target", render: function (row) { return row.target_model; } },
          { label: "Severity", render: function (row) {
              return el("span", { class: row.severity === "blocker" ? "chip chip-unverified" : "chip chip-neutral", text: row.severity });
            } },
          { label: "Result", render: function (row) {
              var className =
                row.status === "pass"
                  ? "chip chip-measured"
                  : row.status === "skip"
                    ? "chip chip-slate"
                    : "chip chip-unverified";
              return el("span", { class: className, text: row.status });
            } },
          { label: "Detail", render: function (row) { return row.message; } },
          { label: "Remediation", render: function (row) { return row.remediation; } }
        ],
        checks,
        { scroll: true, label: "Declared expectations" }
      )
    );

    var sourceCard = card(
      "Delivery sources",
      "Contract version, quality rate and freshness",
      table(
        [
          { label: "Source", render: function (row) { return row.source; } },
          { label: "Entity", render: function (row) { return row.entity; } },
          { label: "Grain", render: function (row) { return (row.grain || []).join(" + "); } },
          { label: "Delivered", numeric: true, key: "rows_delivered" },
          { label: "Published", numeric: true, key: "rows_published" },
          { label: "Rejected", numeric: true, key: "rows_rejected" },
          { label: "Duplicates", numeric: true, key: "duplicates_removed" },
          { label: "Retained", numeric: true, render: function (row) { return format.number(row.retained_pct, 1) + "%"; } },
          { label: "Ingested", render: function (row) { return format.date(row.ingested_at); } }
        ],
        sources,
        { label: "Delivery sources" }
      )
    );

    return el("div", { class: "stack" }, [head, banner, metricCard, checkCard, sourceCard]);
  }

  /* ---------------------------------------------------------------- pipeline */

  function pipeline(bundle) {
    var lineage = bundle.lineage || {};
    var reconciliation = bundle.reconciliation || {};
    var run = bundle.run_metadata || {};
    var models = lineage.models || {};

    var head = el("div", { class: "page-head" }, [
      el("div", { class: "eyebrow", text: "Pipeline & lineage" }),
      el("h1", { text: "From delivery file to published metric" }),
      el("p", {
        text:
          "Every published mart resolves back to a delivery. This page shows the model " +
          "dependencies, the reconciliation ledger and the run that produced the current warehouse."
      })
    ]);

    var runCard = card(
      "Last run",
      run.run_id || "",
      el("dl", { class: "kv" }, [
        el("dt", { text: "Status" }),
        el("dd", { text: run.status || "—" }),
        el("dt", { text: "Run id" }),
        el("dd", { class: "mono", text: run.run_id || "—" }),
        el("dt", { text: "Contract" }),
        el("dd", { class: "mono", text: run.contract_version || "—" }),
        el("dt", { text: "Rows in" }),
        el("dd", { class: "mono", text: format.number(run.rows_in) }),
        el("dt", { text: "Rows published" }),
        el("dd", { class: "mono", text: format.number(run.rows_out) }),
        el("dt", { text: "Rejected" }),
        el("dd", { class: "mono", text: format.number(run.rows_rejected) }),
        el("dt", { text: "Duplicates removed" }),
        el("dd", { class: "mono", text: format.number(run.duplicates_removed) })
      ])
    );

    var modelRows = Object.keys(models)
      .sort()
      .map(function (name) {
        var node = models[name];
        return {
          name: name,
          materialized: node.materialized,
          depends_on_models: node.depends_on_models,
          depends_on_sources: node.depends_on_sources,
          description: node.description
        };
      });

    var modelCard = card(
      "Model lineage",
      "dbt manifest",
      table(
        [
          { label: "Model", render: function (row) { return row.name; } },
          { label: "Materialised as", render: function (row) { return row.materialized; } },
          { label: "Upstream models", render: function (row) { return (row.depends_on_models || []).join(", ") || "—"; } },
          { label: "Delivery sources", render: function (row) { return (row.depends_on_sources || []).join(", ") || "declared"; } }
        ],
        modelRows,
        { scroll: true, label: "Model lineage" }
      )
    );

    var reconciliationRows = Object.keys(reconciliation.sources || {}).map(function (name) {
      var entry = reconciliation.sources[name];
      return {
        source: name,
        entity: entry.entity,
        grain: (entry.grain || []).join(" + "),
        rows_delivered: entry.rows_delivered,
        rows_published: entry.rows_published,
        rows_rejected: entry.rows_rejected,
        duplicates_removed: entry.duplicates_removed,
        retained_pct: entry.retained_pct,
        rejected_pct: entry.rejected_pct
      };
    });

    var reconciliationCard = card(
      "Reconciliation ledger",
      "Delivered, published, rejected",
      table(
        [
          { label: "Source", key: "source" },
          { label: "Entity", key: "entity" },
          { label: "Grain", key: "grain" },
          { label: "Delivered", numeric: true, key: "rows_delivered" },
          { label: "Published", numeric: true, key: "rows_published" },
          { label: "Rejected", numeric: true, key: "rows_rejected" },
          { label: "Duplicates", numeric: true, key: "duplicates_removed" },
          { label: "Retained", numeric: true, render: function (row) { return format.number(row.retained_pct, 1) + "%"; } },
          { label: "Rejected %", numeric: true, render: function (row) { return format.number(row.rejected_pct, 2) + "%"; } }
        ],
        reconciliationRows,
        { label: "Reconciliation ledger" }
      )
    );

    return el("div", { class: "stack" }, [head, el("div", { class: "grid grid-2-1" }, [modelCard, runCard]), reconciliationCard]);
  }

  global.WW.views = global.WW.views || {};
  global.WW.views.simulator = simulator;
  global.WW.views.trust = trustConsole;
  global.WW.views.lineage = pipeline;
})(window);
