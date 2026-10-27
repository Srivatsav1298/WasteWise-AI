/* WasteWiseAI views: overview, waste risk, demand and events.
 *
 * Every value rendered here comes from a published artefact. The views never
 * compute a published metric; they select, filter and lay out what the
 * warehouse already decided.
 */
(function (global) {
  "use strict";

  var data = global.WW.data;
  var charts = global.WW.charts;
  var format = data.format;
  var el = data.el;

  function card(title, note, body) {
    var head = el("div", { class: "card-head" }, [
      el("h2", { text: title }),
      note ? el("span", { class: "card-note", text: note }) : null
    ]);
    return el("section", { class: "card" }, [head, body]);
  }

  function statTile(label, value, unit, meta, trustState) {
    var valueNode = el("div", { class: "stat-value" }, [document.createTextNode(value)]);
    if (unit) {
      valueNode.appendChild(el("span", { class: "unit", text: " " + unit }));
    }
    var children = [
      el("div", { class: "stat-label", text: label }),
      valueNode
    ];
    if (trustState) {
      children.push(el("div", { class: "stat-trust" }, [data.trustChip(trustState)]));
    }
    if (meta) {
      children.push(el("div", { class: "stat-meta", text: meta }));
    }
    return el("section", { class: "card stat" }, children);
  }

  function trustFor(metrics, key) {
    var match = (metrics || []).find(function (metric) {
      return metric.metric_key === key;
    });
    return match ? match.trust_state : null;
  }

  function table(columns, rows, options) {
    options = options || {};
    var head = el("thead", {}, [
      el(
        "tr",
        {},
        columns.map(function (column) {
          return el("th", {
            class: column.numeric ? "num" : "",
            scope: "col",
            text: column.label
          });
        })
      )
    ]);
    var body = el(
      "tbody",
      {},
      rows.map(function (row) {
        return el(
          "tr",
          {},
          columns.map(function (column) {
            var cell = el("td", { class: column.numeric ? "num" : "" });
            var value = column.render ? column.render(row) : row[column.key];
            if (value instanceof Node) {
              cell.appendChild(value);
            } else {
              cell.textContent = value === null || value === undefined ? "—" : String(value);
            }
            return cell;
          })
        );
      })
    );
    // A real caption gives the table an accessible name. It is hidden visually
    // so the visible note keeps its place in the layout.
    var caption = el("caption", { class: "sr-only", text: options.label || "Data table" });
    var tableNode = el("table", { class: "data" }, [caption, head, body]);
    var wrap = el("div", { class: "table-wrap" + (options.scroll ? " scroll-y" : "") }, [
      tableNode
    ]);
    if (options.caption) {
      return el("div", { class: "stack-tight" }, [
        el("p", { class: "card-note", text: options.caption }),
        wrap
      ]);
    }
    return wrap;
  }

  /* -------------------------------------------------------------- overview */

  function overview(bundle) {
    var overviewData = bundle.overview || {};
    var metrics = (bundle.trust_report && bundle.trust_report.metrics) || [];

    var head = el("div", { class: "page-head" }, [
      el("div", { class: "eyebrow", text: "Overview" }),
      el("h1", { text: "Where food value is lost, and how far each number can be trusted" }),
      el("p", {
        text:
          "Cost at risk, waste volume and the prevention backlog for three cafes. " +
          "Every figure below is published by the warehouse and carries a trust state."
      })
    ]);

    var costRow = (overviewData.waste_cost_at_risk || [])[0] || {};
    var quantityRow = (overviewData.waste_quantity || [])[0] || {};
    var avoidableRow = (overviewData.avoidable_share || [])[0] || {};
    var rateRow = (overviewData.waste_rate_per_demand || [])[0] || {};

    var tiles = el("div", { class: "grid grid-4" }, [
      statTile(
        "Avoidable waste cost",
        format.money(costRow.value),
        null,
        format.number(costRow.rows_measured) + " avoidable waste events",
        trustFor(metrics, "waste_cost_at_risk")
      ),
      statTile(
        "Waste recorded",
        format.number(quantityRow.value, 1),
        "kg or units",
        format.number(quantityRow.rows_measured) + " waste events",
        trustFor(metrics, "waste_quantity")
      ),
      statTile(
        "Avoidable cost share",
        format.percent(avoidableRow.value),
        null,
        "reason classification, not a measurement",
        trustFor(metrics, "avoidable_cost_share")
      ),
      statTile(
        "Waste per unit of demand",
        format.percent(rateRow.value),
        null,
        "total waste over total demand of the same ingredients",
        trustFor(metrics, "waste_rate_per_demand")
      )
    ]);

    var trend = overviewData.daily_trend || [];
    var dates = [];
    var seenDates = {};
    var byLocation = {};
    trend.forEach(function (row) {
      var day = String(row.waste_date).slice(0, 10);
      if (!seenDates[day]) {
        seenDates[day] = true;
        dates.push(day);
      }
      if (!byLocation[row.location_id]) {
        byLocation[row.location_id] = {};
      }
      byLocation[row.location_id][day] = row.waste_quantity;
    });
    dates.sort();
    var series = Object.keys(byLocation).sort().map(function (key, index) {
      return {
        name: format.titleCase(key.replace(/_/g, " ")),
        values: dates.map(function (day) {
          return byLocation[key][day] || 0;
        }),
        color: charts.palette[index % charts.palette.length]
      };
    });
    var labels = dates.map(function (day) {
      return day.slice(5);
    });

    var trendCard = card(
      "Daily waste quantity by cafe",
      "45 days · rolling series",
      charts.lineChart({
        series: series,
        labels: labels,
        ariaLabel: "Daily waste quantity per cafe over the delivered window"
      })
    );

    var topIngredients = (overviewData.top_ingredients || []).slice(0, 8);
    var ingredientCard = card(
      "Cost at risk by ingredient",
      "Top 8",
      charts.barChart({
        rows: topIngredients.map(function (row) {
          return {
            label: row.ingredient_name,
            value: row.waste_cost,
            display: format.money(row.waste_cost)
          };
        }),
        ariaLabel: "Waste cost by ingredient"
      })
    );

    var locationRows = overviewData.locations || [];
    var locationCard = card(
      "Cafe breakdown",
      "Published per location",
      table(
        [
          { label: "Cafe", render: function (row) { return row.location_name || format.titleCase(row.location_id); } },
          { label: "City", render: function (row) { return row.city || "—"; } },
          { label: "Waste cost", numeric: true, render: function (row) { return format.money(row.waste_cost); } },
          { label: "Quantity", numeric: true, render: function (row) { return format.number(row.waste_quantity, 1); } },
          { label: "Per demand", numeric: true, render: function (row) { return format.percent(row.waste_rate_per_demand); } },
          { label: "Events", numeric: true, key: "events" }
        ],
        locationRows,
        { label: "Waste by cafe" }
      )
    );

    return el("div", { class: "stack" }, [
      head,
      tiles,
      el("div", { class: "grid grid-2" }, [trendCard, ingredientCard]),
      locationCard
    ]);
  }

  /* ------------------------------------------------------------ waste risk */

  function wasteRisk(bundle) {
    var priority = bundle.waste_priority || [];
    var byReason = bundle.waste_by_reason || [];
    var byCategory = bundle.waste_by_category || [];

    var head = el("div", { class: "page-head" }, [
      el("div", { class: "eyebrow", text: "Waste risk" }),
      el("h1", { text: "The prevention backlog, ranked by money and avoidability" }),
      el("p", {
        text:
          "Each row is one waste event priced at purchase-unit cost. The ranking multiplies " +
          "cost, avoidability and data coverage, so a row that cannot be priced never reaches the top."
      })
    ]);

    var state = { location: "all", reason: "all", ingredient: "all" };
    var tableHost = el("div", {});

    function filtered() {
      return priority.filter(function (row) {
        if (state.location !== "all" && row.location_id !== state.location) {
          return false;
        }
        if (state.reason !== "all" && row.waste_reason !== state.reason) {
          return false;
        }
        if (state.ingredient !== "all" && row.ingredient_id !== state.ingredient) {
          return false;
        }
        return true;
      });
    }

    function renderTable() {
      var rows = filtered().slice(0, 60);
      tableHost.innerHTML = "";
      tableHost.appendChild(
        table(
          [
            { label: "#", numeric: true, render: function (row) { return String(row.priority_rank); } },
            { label: "Date", render: function (row) { return format.date(row.waste_date); } },
            { label: "Cafe", render: function (row) { return format.titleCase(row.location_id); } },
            { label: "Ingredient", render: function (row) { return row.ingredient_name; } },
            { label: "Reason", render: function (row) { return format.titleCase(row.waste_reason); } },
            { label: "Cost", numeric: true, render: function (row) { return format.money(row.estimated_cost); } },
            { label: "Avoidable", render: function (row) { return format.titleCase(row.avoidability); } },
            { label: "Trust", render: function (row) { return data.trustChip(row.trust_state); } }
          ],
          rows,
          { scroll: true, caption: "Top 60 of the filtered backlog", label: "Ranked prevention backlog" }
        )
      );
    }

    function select(label, options, key) {
      var node = el("select", {
        id: "filter-" + key,
        onchange: function (event) {
          state[key] = event.target.value;
          renderTable();
        }
      });
      options.forEach(function (option) {
        var element = el("option", { value: option.value, text: option.label });
        if (option.value === state[key]) {
          element.selected = true;
        }
        node.appendChild(element);
      });
      return el("div", { class: "field" }, [
        el("label", { for: "filter-" + key, text: label }),
        node
      ]);
    }

    function unique(field) {
      var values = {};
      priority.forEach(function (row) {
        values[row[field]] = true;
      });
      return Object.keys(values).sort();
    }

    var filters = el("div", { class: "filters" }, [
      select("Cafe", [{ value: "all", label: "All cafes" }].concat(unique("location_id").map(function (value) {
        return { value: value, label: format.titleCase(value) };
      })), "location"),
      select("Reason", [{ value: "all", label: "All reasons" }].concat(unique("waste_reason").map(function (value) {
        return { value: value, label: format.titleCase(value) };
      })), "reason"),
      select("Ingredient", [{ value: "all", label: "All ingredients" }].concat(unique("ingredient_id").map(function (value) {
        return { value: value, label: format.titleCase(value) };
      })), "ingredient")
    ]);

    renderTable();

    var reasonCard = card(
      "Waste cost by reason",
      "Published totals",
      charts.donutChart({
        rows: byReason.map(function (row, index) {
          return {
            label: row.waste_reason,
            value: row.total_cost,
            color: charts.palette[index % charts.palette.length]
          };
        }),
        centerLabel: "Reasons",
        centerValue: String(byReason.length),
        ariaLabel: "Share of waste cost by reason"
      })
    );

    var reasonTable = card(
      "Reason policy",
      "Avoidability and the lever that removes it",
      table(
        [
          { label: "Reason", render: function (row) { return format.titleCase(row.waste_reason); } },
          { label: "Avoidability", render: function (row) { return format.titleCase(row.avoidability); } },
          { label: "Cost", numeric: true, render: function (row) { return format.money(row.total_cost); } },
          { label: "Events", numeric: true, key: "waste_event_count" },
          { label: "Lever", render: function (row) { return row.prevention_lever; } }
        ],
        byReason,
        { label: "Waste cost by reason" }
      )
    );

    var categoryCard = card(
      "Waste cost by ingredient category",
      null,
      charts.barList(
        byCategory.map(function (row, index) {
          return {
            label: row.category,
            value: row.total_cost,
            display: format.money(row.total_cost),
            color: charts.palette[index % charts.palette.length]
          };
        })
      )
    );

    return el("div", { class: "stack" }, [
      head,
      filters,
      el("section", { class: "card" }, [
        el("div", { class: "card-head" }, [
          el("h2", { text: "Ranked prevention backlog" }),
          el("span", { class: "card-note", text: "cost x avoidability x coverage" })
        ]),
        tableHost
      ]),
      el("div", { class: "grid grid-2" }, [reasonCard, categoryCard]),
      reasonTable
    ]);
  }

  /* ------------------------------------------------------- demand & events */

  function demandEvents(bundle) {
    var events = bundle.demand_events || [];
    var metrics = (bundle.trust_report && bundle.trust_report.metrics) || [];
    var measured = events.filter(function (row) {
      return !row.is_forward_looking;
    });
    var upcoming = events.filter(function (row) {
      return row.is_forward_looking;
    });

    var head = el("div", { class: "page-head" }, [
      el("div", { class: "eyebrow", text: "Demand & events" }),
      el("h1", { text: "What the calendar did to demand, and what it has not done yet" }),
      el("p", {
        text:
          "Measured lift comes from delivered sales around an event. Events after the data " +
          "window carry an attendance signal only: no lift is published for them, because a " +
          "forecast is not a measurement."
      })
    ]);

    var liftRows = measured
      .filter(function (row) {
        return row.demand_lift_pct !== null && row.demand_lift_pct !== undefined;
      })
      .sort(function (a, b) {
        return b.demand_lift_pct - a.demand_lift_pct;
      });

    var liftCard = card(
      "Measured demand lift around events",
      "Units sold per day, 7 day window vs 17 day baseline",
      charts.barChart({
        rows: liftRows.map(function (row) {
          return {
            label: row.event_name.slice(0, 20) + " · " + format.titleCase(row.location_id),
            value: row.demand_lift_pct,
            display: "+" + format.number(row.demand_lift_pct, 1) + "%"
          };
        }),
        color: charts.palette[1],
        ariaLabel: "Measured demand lift by event and cafe"
      })
    );

    var measuredCard = card(
      "Events inside the data window",
      null,
      table(
        [
          { label: "Event", render: function (row) { return row.event_name; } },
          { label: "Date", render: function (row) { return format.date(row.event_date); } },
          { label: "Cafe", render: function (row) { return row.location_name; } },
          { label: "Lift / day", numeric: true, render: function (row) { return format.lift(row.demand_lift_pct); } },
          { label: "Window units", numeric: true, render: function (row) { return format.number(row.window_units_sold); } },
          { label: "Baseline / day", numeric: true, render: function (row) { return format.number(row.baseline_daily_units, 1); } },
          { label: "Waste in window", numeric: true, render: function (row) { return format.money(row.window_waste_cost); } }
        ],
        measured,
        { label: "Events inside the data window" }
      )
    );

    var upcomingCard = card(
      "Upcoming events",
      "Signal only, no published lift",
      table(
        [
          { label: "Event", render: function (row) { return row.event_name; } },
          { label: "Date", render: function (row) { return format.date(row.event_date); } },
          { label: "Venue", render: function (row) { return row.venue; } },
          { label: "Cafe", render: function (row) { return row.location_name; } },
          { label: "Expected attendance", numeric: true, render: function (row) { return format.number(row.expected_attendance); } },
          { label: "Attendance", render: function (row) { return data.trustChip(row.attendance_confidence === "unknown" ? "unverified" : "partial", row.attendance_confidence + " confidence"); } }
        ],
        upcoming,
        {
          label: "Upcoming events",
          caption:
            "Attendance is an organiser estimate. The trust state shows how much of it can be relied on."
        }
      )
    );

    var plan = bundle.purchase_plan || [];
    var orderMetric = metrics.find(function (metric) {
      return metric.metric_key === "recommended_order_qty";
    });
    var planPublished = orderMetric ? orderMetric.displayable !== false : true;
    var orderRows = plan.filter(function (row) {
      return row.recommended_order_qty !== null && Number(row.recommended_order_qty) > 0;
    });
    var reduceRows = plan.filter(function (row) {
      return row.purchase_action === "reduce_order";
    });
    var watchRows = plan.filter(function (row) {
      return row.purchase_action === "watch";
    });
    var orderCost = orderRows.reduce(function (sum, row) {
      return sum + Number(row.recommended_order_cost || 0);
    }, 0);

    var planTiles = el("div", { class: "grid grid-3" }, [
      statTile(
        "Order to place",
        planPublished ? format.money(orderCost) : "not published",
        null,
        planPublished
          ? format.number(orderRows.length) + " ingredient lines need a purchase"
          : "the trust engine does not allow this metric to be shown",
        trustFor(metrics, "recommended_order_qty")
      ),
      statTile(
        "Order lines to reduce",
        format.number(reduceRows.length),
        null,
        "waste rate above 8% of demand",
        null
      ),
      statTile(
        "Lines to watch",
        format.number(watchRows.length),
        null,
        "waste rate between 3% and 8%",
        null
      )
    ]);

    var planCard = card(
      "Purchase plan",
      "Planning aid, not a forecast",
      el("div", { class: "stack" }, [
        table(
          [
            { label: "Cafe", render: function (row) { return row.location_name; } },
            { label: "Ingredient", render: function (row) { return row.ingredient_name; } },
            { label: "On hand", numeric: true, render: function (row) { return format.number(row.stock_on_hand, 1) + " " + row.ingredient_unit; } },
            { label: "Demand 30d", numeric: true, render: function (row) { return format.number(row.demand_qty_30d, 1) + " " + row.ingredient_unit; } },
            { label: "Waste rate", numeric: true, render: function (row) { return format.percent(row.waste_rate_30d); } },
            { label: "Order", numeric: true, render: function (row) {
                return row.recommended_order_qty === null
                  ? "not published"
                  : format.number(row.recommended_order_qty, 1) + " " + row.ingredient_unit;
              } },
            { label: "Cost", numeric: true, render: function (row) { return format.money(row.recommended_order_cost); } }
          ],
          orderRows,
          {
            label: "Recommended purchase orders",
            caption:
              "Cover days of average demand minus stock on hand. A planning heuristic with an " +
              "explainable formula, never a forecast of demand."
          }
        ),
        table(
          [
            { label: "Cafe", render: function (row) { return row.location_name; } },
            { label: "Ingredient", render: function (row) { return row.ingredient_name; } },
            { label: "Waste rate 30d", numeric: true, render: function (row) { return format.percent(row.waste_rate_30d); } },
            { label: "Waste cost 30d", numeric: true, render: function (row) { return format.money(row.waste_cost_30d); } },
            { label: "Last waste", render: function (row) { return format.date(row.last_waste_date); } }
          ],
          reduceRows,
          {
            label: "Order lines to reduce",
            caption:
              "Order lines whose 30 day waste rate is above 8% of demand. Ordering down here " +
              "is the cheapest lever the data supports."
          }
        )
      ])
    );

    return el("div", { class: "stack" }, [
      head,
      el("div", { class: "grid grid-2" }, [liftCard, measuredCard]),
      upcomingCard,
      planTiles,
      planCard
    ]);
  }

  global.WW = global.WW || {};
  global.WW.views = global.WW.views || {};
  global.WW.views.overview = overview;
  global.WW.views["waste-risk"] = wasteRisk;
  global.WW.views["demand-events"] = demandEvents;
  global.WW.views.table = table;
  global.WW.views.card = card;
  global.WW.views.statTile = statTile;
  global.WW.views.trustFor = trustFor;
})(window);
