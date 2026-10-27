/* WasteWiseAI charts.
 *
 * Hand rolled SVG: no chart library, no runtime dependency, full control over
 * the visual language. Every chart returns a DOM node, is labelled for screen
 * readers, and respects the reduced motion preference.
 */
(function (global) {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var PALETTE = ["#1f4a38", "#b4691a", "#46566b", "#9b3b26", "#4f7a5f", "#c99a4a", "#7d8ca0", "#6b4a2f"];

  function svgNode(tag, attributes) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attributes || {}).forEach(function (key) {
      if (attributes[key] !== null && attributes[key] !== undefined) {
        node.setAttribute(key, String(attributes[key]));
      }
    });
    return node;
  }

  function niceCeiling(value) {
    if (!value || value <= 0) {
      return 1;
    }
    var magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    var scaled = value / magnitude;
    var step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
    return step * magnitude;
  }

  function axisTicks(maxValue, count) {
    var top = niceCeiling(maxValue);
    var ticks = [];
    for (var index = 0; index <= count; index += 1) {
      ticks.push((top / count) * index);
    }
    return ticks;
  }

  function formatTick(value) {
    if (value >= 1000) {
      return Math.round(value).toLocaleString("en-GB");
    }
    if (value >= 10) {
      return String(Math.round(value));
    }
    return String(Math.round(value * 10) / 10);
  }

  /* ------------------------------------------------------------- line chart */

  function lineChart(options) {
    var series = options.series || [];
    var width = options.width || 720;
    var height = options.height || 260;
    var padding = { top: 16, right: 16, bottom: 28, left: 52 };
    var plotWidth = width - padding.left - padding.right;
    var plotHeight = height - padding.top - padding.bottom;
    var labels = options.labels || [];

    var maximum = 0;
    series.forEach(function (entry) {
      entry.values.forEach(function (value) {
        if (value > maximum) {
          maximum = value;
        }
      });
    });
    var ticks = axisTicks(maximum, 4);
    var top = ticks[ticks.length - 1] || 1;

    var svg = svgNode("svg", {
      class: "chart",
      viewBox: "0 0 " + width + " " + height,
      role: "img",
      "aria-label": options.ariaLabel || "Line chart"
    });

    ticks.forEach(function (tick) {
      var y = padding.top + plotHeight - (tick / top) * plotHeight;
      svg.appendChild(
        svgNode("line", {
          class: "grid-line",
          x1: padding.left,
          x2: width - padding.right,
          y1: y,
          y2: y
        })
      );
      var label = svgNode("text", { x: padding.left - 8, y: y + 3, "text-anchor": "end" });
      label.textContent = formatTick(tick);
      svg.appendChild(label);
    });

    series.forEach(function (entry, seriesIndex) {
      var points = entry.values.map(function (value, index) {
        var x =
          padding.left +
          (labels.length > 1 ? (index / (labels.length - 1)) * plotWidth : plotWidth / 2);
        var y = padding.top + plotHeight - (value / top) * plotHeight;
        return { x: x, y: y };
      });
      if (points.length > 1) {
        var path = points
          .map(function (point, index) {
            return (index === 0 ? "M" : "L") + point.x.toFixed(1) + " " + point.y.toFixed(1);
          })
          .join(" ");
        svg.appendChild(
          svgNode("path", {
            d: path,
            fill: "none",
            stroke: entry.color || PALETTE[seriesIndex % PALETTE.length],
            "stroke-width": 2,
            "stroke-linejoin": "round",
            "stroke-linecap": "round"
          })
        );
      }
      points.forEach(function (point) {
        svg.appendChild(
          svgNode("circle", {
            cx: point.x,
            cy: point.y,
            r: 2.6,
            fill: entry.color || PALETTE[seriesIndex % PALETTE.length]
          })
        );
      });
    });

    if (labels.length) {
      var step = Math.max(1, Math.ceil(labels.length / 7));
      labels.forEach(function (label, index) {
        if (index % step !== 0 && index !== labels.length - 1) {
          return;
        }
        var x =
          padding.left +
          (labels.length > 1 ? (index / (labels.length - 1)) * plotWidth : plotWidth / 2);
        var text = svgNode("text", { x: x, y: height - 8, "text-anchor": "middle" });
        text.textContent = label;
        svg.appendChild(text);
      });
    }

    var axis = svgNode("g", { class: "axis" });
    axis.appendChild(
      svgNode("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: padding.top + plotHeight,
        y2: padding.top + plotHeight
      })
    );
    svg.appendChild(axis);

    return withLegend(svg, series);
  }

  /* ------------------------------------------------------------- bar chart */

  function barChart(options) {
    var rows = options.rows || [];
    var width = options.width || 720;
    var height = options.height || 260;
    var padding = { top: 12, right: 16, bottom: 44, left: 120 };
    var plotWidth = width - padding.left - padding.right;
    var plotHeight = height - padding.top - padding.bottom;
    var maximum = rows.reduce(function (carry, row) {
      return Math.max(carry, row.value);
    }, 0);
    var top = niceCeiling(maximum);

    var svg = svgNode("svg", {
      class: "chart",
      viewBox: "0 0 " + width + " " + height,
      role: "img",
      "aria-label": options.ariaLabel || "Bar chart"
    });

    var bandHeight = plotHeight / Math.max(rows.length, 1);
    rows.forEach(function (row, index) {
      var barHeight = Math.min(18, bandHeight * 0.62);
      var y = padding.top + index * bandHeight + (bandHeight - barHeight) / 2;
      var barWidth = top ? (row.value / top) * plotWidth : 0;
      svg.appendChild(
        svgNode("rect", {
          x: padding.left,
          y: y,
          width: Math.max(barWidth, 1),
          height: barHeight,
          rx: 2,
          fill: row.color || options.color || PALETTE[0]
        })
      );
      var label = svgNode("text", {
        x: padding.left - 10,
        y: y + barHeight / 2 + 3,
        "text-anchor": "end"
      });
      label.textContent = row.label;
      svg.appendChild(label);
      var value = svgNode("text", {
        x: padding.left + Math.max(barWidth, 1) + 6,
        y: y + barHeight / 2 + 3
      });
      value.textContent = row.display || formatTick(row.value);
      svg.appendChild(value);
    });

    var axis = svgNode("g", { class: "axis" });
    axis.appendChild(
      svgNode("line", {
        x1: padding.left,
        x2: padding.left,
        y1: padding.top,
        y2: padding.top + plotHeight
      })
    );
    svg.appendChild(axis);
    return svg;
  }

  /* ---------------------------------------------------------- stacked bars */

  function stackedBars(options) {
    var groups = options.groups || [];
    var series = options.series || [];
    var width = options.width || 720;
    var height = options.height || 260;
    var padding = { top: 12, right: 16, bottom: 40, left: 52 };
    var plotWidth = width - padding.left - padding.right;
    var plotHeight = height - padding.top - padding.bottom;

    var totals = groups.map(function (group) {
      return group.segments.reduce(function (carry, segment) {
        return carry + segment.value;
      }, 0);
    });
    var maximum = totals.reduce(function (carry, value) {
      return Math.max(carry, value);
    }, 0);
    var top = niceCeiling(maximum);

    var svg = svgNode("svg", {
      class: "chart",
      viewBox: "0 0 " + width + " " + height,
      role: "img",
      "aria-label": options.ariaLabel || "Stacked bar chart"
    });

    axisTicks(maximum, 4).forEach(function (tick) {
      var y = padding.top + plotHeight - (tick / top) * plotHeight;
      svg.appendChild(
        svgNode("line", {
          class: "grid-line",
          x1: padding.left,
          x2: width - padding.right,
          y1: y,
          y2: y
        })
      );
      var label = svgNode("text", { x: padding.left - 8, y: y + 3, "text-anchor": "end" });
      label.textContent = formatTick(tick);
      svg.appendChild(label);
    });

    var bandWidth = plotWidth / Math.max(groups.length, 1);
    var barWidth = Math.min(46, bandWidth * 0.56);
    groups.forEach(function (group, index) {
      var x = padding.left + index * bandWidth + (bandWidth - barWidth) / 2;
      var cursor = padding.top + plotHeight;
      group.segments.forEach(function (segment, segmentIndex) {
        var segmentHeight = top ? (segment.value / top) * plotHeight : 0;
        cursor -= segmentHeight;
        svg.appendChild(
          svgNode("rect", {
            x: x,
            y: cursor,
            width: barWidth,
            height: Math.max(segmentHeight, 0),
            fill: segment.color || PALETTE[segmentIndex % PALETTE.length]
          })
        );
      });
      var label = svgNode("text", {
        x: x + barWidth / 2,
        y: height - 18,
        "text-anchor": "middle"
      });
      label.textContent = group.label;
      svg.appendChild(label);
    });

    return withLegend(svg, series);
  }

  /* ------------------------------------------------------------ donut chart */

  function donutChart(options) {
    var rows = options.rows || [];
    var size = options.size || 190;
    var thickness = options.thickness || 30;
    var radius = size / 2;
    var inner = radius - thickness;
    var total = rows.reduce(function (carry, row) {
      return carry + row.value;
    }, 0);

    var svg = svgNode("svg", {
      class: "chart",
      viewBox: "0 0 " + size + " " + size,
      role: "img",
      "aria-label": options.ariaLabel || "Donut chart"
    });

    var angle = -Math.PI / 2;
    rows.forEach(function (row, index) {
      if (!total) {
        return;
      }
      var slice = (row.value / total) * Math.PI * 2;
      var end = angle + slice;
      var path = svgNode("path", {
        d:
          "M " +
          (radius + radius * Math.cos(angle)).toFixed(2) +
          " " +
          (radius + radius * Math.sin(angle)).toFixed(2) +
          " A " +
          radius +
          " " +
          radius +
          " 0 " +
          (slice > Math.PI ? 1 : 0) +
          " 1 " +
          (radius + radius * Math.cos(end)).toFixed(2) +
          " " +
          (radius + radius * Math.sin(end)).toFixed(2) +
          " L " +
          (radius + inner * Math.cos(end)).toFixed(2) +
          " " +
          (radius + inner * Math.sin(end)).toFixed(2) +
          " A " +
          inner +
          " " +
          inner +
          " 0 " +
          (slice > Math.PI ? 1 : 0) +
          " 0 " +
          (radius + inner * Math.cos(angle)).toFixed(2) +
          " " +
          (radius + inner * Math.sin(angle)).toFixed(2) +
          " Z",
        fill: row.color || PALETTE[index % PALETTE.length]
      });
      svg.appendChild(path);
      angle = end;
    });

    if (options.centerLabel) {
      var title = svgNode("text", {
        x: radius,
        y: radius - 2,
        "text-anchor": "middle",
        class: "series-label"
      });
      title.textContent = options.centerLabel;
      svg.appendChild(title);
      var sub = svgNode("text", { x: radius, y: radius + 14, "text-anchor": "middle" });
      sub.textContent = options.centerValue || "";
      svg.appendChild(sub);
    }

    return svg;
  }

  /* ---------------------------------------------------------------- legend */

  function withLegend(svg, series) {
    if (!series || !series.length) {
      return svg;
    }
    var wrapper = document.createElement("div");
    wrapper.appendChild(svg);
    var legend = document.createElement("div");
    legend.className = "legend";
    series.forEach(function (entry, index) {
      var item = document.createElement("span");
      item.className = "legend-item";
      var swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = entry.color || PALETTE[index % PALETTE.length];
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(entry.name));
      legend.appendChild(item);
    });
    wrapper.appendChild(legend);
    return wrapper;
  }

  function barList(rows, options) {
    var wrapper = document.createElement("div");
    var maximum = rows.reduce(function (carry, row) {
      return Math.max(carry, row.value);
    }, 0);
    rows.forEach(function (row) {
      var line = document.createElement("div");
      line.className = "bar-row";
      var label = document.createElement("div");
      label.className = "bar-label";
      label.textContent = row.label;
      var track = document.createElement("div");
      track.className = "bar-track";
      var fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.width = (maximum ? (row.value / maximum) * 100 : 0).toFixed(1) + "%";
      if (row.color) {
        fill.style.background = row.color;
      }
      track.appendChild(fill);
      var value = document.createElement("div");
      value.className = "bar-value";
      value.textContent = row.display || String(row.value);
      line.appendChild(label);
      line.appendChild(track);
      line.appendChild(value);
      wrapper.appendChild(line);
    });
    if (options && options.note) {
      var note = document.createElement("p");
      note.className = "card-note";
      note.textContent = options.note;
      wrapper.appendChild(note);
    }
    return wrapper;
  }

  global.WW = global.WW || {};
  global.WW.charts = {
    lineChart: lineChart,
    barChart: barChart,
    stackedBars: stackedBars,
    donutChart: donutChart,
    barList: barList,
    palette: PALETTE
  };
})(window);
