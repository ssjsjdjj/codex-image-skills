/* S3–S5 bindings for 小山行风感洞洞裤-终.psb. Only the inner tables are rebuilt. */
function rebuildPantsDetailTables(doc, tables, fonts) {
    var root = findLayer(doc, ["尺码"]);
    var specs = [
        {
            key: "03选尺码", section: "3", base: ["矩形 959 拷贝 4"],
            obsolete: ["矩形 959 拷贝 4", "矩形 2101", "矩形 2107", "矩形 2107 拷贝",
                       "矩形 2107 拷贝 2", "尺码", "组 841 拷贝 3", "组 1004", "组 1003",
                       "组 1003 拷贝", "组 1003 拷贝 2", "组 1003 拷贝 3", "组 1003 拷贝 4"],
            headerHeight: 80, headerMin: 44, rowHeight: 54, px: 24, accent: false
        },
        {
            key: "05尺码快选", section: "4", base: ["组 1262", "矩形 959 拷贝 4"],
            obsolete: ["组 1262", "组 841 拷贝 3", "组 1004", "身高/体重"],
            headerHeight: 64, headerMin: 36, rowHeight: 65, px: 21, accent: true
        },
        {
            key: "试穿报告", section: "5", base: ["组 1263", "矩形 959 拷贝 4"],
            obsolete: ["组 1263"], headerHeight: 40, headerMin: 31, rowHeight: 35,
            px: 18, accent: true
        }
    ];
    var built = 0;
    for (var i = 0; i < specs.length; i++) {
        var spec = specs[i];
        var section = findLayer(root, [spec.section]);
        var matrix = tables[spec.key];
        if (!matrix) {
            section.visible = false;
            continue;
        }
        var originalBase = findLayer(section, spec.base);
        var region = box(originalBase);
        var widths = measurePantsDetailColumns(section, matrix, region, spec, fonts);
        var plan = planPantsDetailTable(matrix.length - 1, widths, region[2] - region[0], region[3] - region[1], spec);
        if (spec.section === "4") {
            // Unit annotation shares a group with the old data cells.
            var units = findLayer(section, ["组 1004", "身高cm/体重kg"]);
            units.move(section, ElementPlacement.INSIDE);
        }
        var table = section.layerSets.add();
        table.name = spec.key + "（可编辑）";
        var base = originalBase.duplicate(table, ElementPlacement.INSIDE);
        base.name = "原母版圆角表底";
        for (var j = 0; j < spec.obsolete.length; j++) findLayer(section, [spec.obsolete[j]]).remove();
        drawPantsDetailTable(doc, table, base, matrix, region, plan, spec, fonts);
        built++;
    }
    return built;
}

function pantsCellFont(value, fonts) {
    return /[^\x00-\x7f]/.test(value) ? fonts.cn.postScriptName : fonts.latin.postScriptName;
}

function measurePantsDetailColumns(section, matrix, region, spec, fonts) {
    var probe = section.layerSets.add();
    var cache = {};
    var widths = [];
    var columns = matrix[0].length;
    for (var c = 0; c < columns; c++) widths.push(0);
    try {
        for (var r = 0; r < matrix.length; r++) {
            if (matrix[r].length !== columns) throw new Error(spec.key + "各行的列数必须一致。");
            for (c = 0; c < columns; c++) {
                var value = nativeDetailCell(matrix[r][c]);
                if (value === " ") continue;
                var key = "$" + value;
                if (cache[key] === undefined) {
                    var sample = tableText(probe, "测量", value, (region[0] + region[2]) / 2,
                                           region[1] + 35, 5000, spec.px, [0, 0, 0],
                                           pantsCellFont(value, fonts), Justification.CENTER, fonts);
                    var bounds = box(sample);
                    cache[key] = bounds[2] - bounds[0];
                    sample.remove();
                }
                widths[c] = Math.max(widths[c], cache[key]);
            }
        }
    } finally {
        probe.remove();
    }
    return widths;
}

function planPantsDetailTable(rowCount, demands, width, height, spec) {
    var columns = demands.length;
    var minRow = 23;
    var header = Math.min(spec.headerHeight, height - minRow * rowCount);
    if (header < spec.headerMin) {
        throw new Error(spec.key + "的 " + rowCount + " 行超出本区可读范围，请分表或给该模块扩高。");
    }
    var rowHeight = Math.min(Math.round(spec.rowHeight * 1.35), Math.floor((height - header) / rowCount));
    var px = Math.min(spec.px, rowHeight - 7, header - 9);
    var minimumPx = 16;
    var padding = columns > 9 ? 10 : 16;
    var widths;
    var total;
    while (px >= minimumPx) {
        widths = [];
        total = 0;
        for (var c = 0; c < columns; c++) {
            var minWidth = Math.max(36, Math.ceil(demands[c] * px / spec.px) + padding);
            widths.push(minWidth);
            total += minWidth;
        }
        if (total <= width) break;
        px--;
    }
    if (px < minimumPx) throw new Error(spec.key + "的列内容超出本区可读宽度，请按指标分表。");
    // Equal widths where possible; wide headings and feedback only claim the space they need.
    var sorted = widths.slice().sort(function (a, b) { return a - b; });
    var remaining = width - total;
    for (c = 0; c < sorted.length - 1 && remaining > 0; c++) {
        var increment = Math.min(sorted[c + 1] - sorted[c], remaining / (c + 1));
        for (var n = 0; n <= c; n++) sorted[n] += increment;
        remaining -= increment * (c + 1);
    }
    var target = sorted[0] + remaining / columns;
    var used = 0;
    for (c = 0; c < columns; c++) {
        widths[c] = Math.max(widths[c], target);
        used += widths[c];
    }
    // The final equal share also covers the leftover from raising narrow columns to the floor.
    for (c = 0; c < columns; c++) widths[c] += (width - used) / columns;
    return {header: header, row: rowHeight, px: px, widths: widths, height: header + rowCount * rowHeight};
}

function pantsTableBand(doc, table, anchor, name, x, y, w, h, color) {
    var band = rectangle(doc, table, name, x, y, w, h, color);
    band.move(anchor, ElementPlacement.PLACEBEFORE);
    if (!band.grouped) band.grouped = true;
    return band;
}

function drawPantsDetailTable(doc, table, base, matrix, region, plan, spec, fonts) {
    var x = region[0];
    var y = region[1];
    var w = region[2] - x;
    var oldHeight = region[3] - y;
    if (plan.height !== oldHeight) {
        base.resize(100, plan.height / oldHeight * 100, AnchorPosition.TOPCENTER);
        var top = box(base)[1];
        if (top !== y) base.translate(UnitValue(0, "px"), UnitValue(y - top, "px"));
    }
    var topBand = pantsTableBand(doc, table, base, "表头底色", x, y, w, plan.header,
                                 spec.accent ? [46, 158, 73] : [237, 237, 237]);
    for (var r = 1; r < matrix.length; r++) {
        var rowY = y + plan.header + (r - 1) * plan.row;
        if (r % 2 === 0) pantsTableBand(doc, table, base, "交替行底色 " + r, x, rowY, w, plan.row,
                                       [248, 248, 248]);
    }
    if (spec.accent) {
        var lead = pantsTableBand(doc, table, base, "行标底色", x, y + plan.header, plan.widths[0],
                                  plan.height - plan.header, [232, 232, 232]);
        lead.move(topBand, ElementPlacement.PLACEBEFORE);
        for (r = 1; r < matrix.length - 1; r++) {
            var line = pantsTableBand(doc, table, base, "行间隔线 " + r, x,
                                      y + plan.header + r * plan.row - 1, w, 2, [247, 247, 247]);
            line.move(lead, ElementPlacement.PLACEBEFORE);
        }
    }
    for (r = 0; r < matrix.length; r++) {
        var row = table.layerSets.add();
        row.name = r === 0 ? "表头" : "第 " + r + " 行";
        var bandTop = r === 0 ? y : y + plan.header + (r - 1) * plan.row;
        var bandHeight = r === 0 ? plan.header : plan.row;
        var left = x;
        for (var c = 0; c < plan.widths.length; c++) {
            var value = nativeDetailCell(matrix[r][c]);
            var font = pantsCellFont(value, fonts);
            var cell = tableText(row, "第 " + (c + 1) + " 列", value, left + plan.widths[c] / 2,
                                 bandTop + bandHeight / 2 + plan.px * 0.33, plan.widths[c] - 8, plan.px,
                                 spec.accent && r === 0 ? [255, 255, 255] : [54, 54, 54], font,
                                 Justification.CENTER, fonts);
            if (value !== " ") {
                var actual = box(cell);
                if (cell.textItem.size.as("pt") * doc.resolution / 72 < 15.5) {
                    throw new Error(spec.key + " 第 " + (c + 1) + " 列文字过密，请按指标分表。");
                }
                if (actual[1] < bandTop + 1 || actual[3] > bandTop + bandHeight - 1) {
                    throw new Error(spec.key + " 第 " + (r + 1) + " 行文字超出行高，请分表或扩高本区。");
                }
            }
            left += plan.widths[c];
        }
    }
}

function pantsDetailMixedProductPath(path) {
    if (path.length < 3 || path[0] !== "产品信息") return false;
    var name = path[path.length - 1].replace(/^\s+|\s+$/g, "");
    return /^([A-Za-z]{1,4}[0-9]{4,}|均码|[0-9]{2,3}[-–][0-9]{2,3})$/.test(name) ||
           /材质|面料|纤维|%/.test(name);
}
