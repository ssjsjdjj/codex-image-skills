/* Bind the earlier 产品信息 / 产品信息T family through its named editable modules. */
function optionalClassicLayer(parent, name) {
    var result = null;
    for (var i = 0; i < parent.layers.length; i++) {
        if (parent.layers[i].name === name) {
            if (result) throw new Error("母版图层重名：" + name);
            result = parent.layers[i];
        }
    }
    return result;
}

function classicEditableTable(parent, name) {
    // Accept this known native-table variant only within its anchored classic
    // parent. Similar names elsewhere in the document are not candidates.
    var group = optionalClassicLayer(parent, name + "（可编辑）");
    if (!group) return null;
    if (group.typename !== "LayerSet") throw new Error("表格容器类型暂未识别：" + name + "（可编辑）");
    var base = findLayer(group, ["表格底"]);
    var header = findLayer(group, ["表头"]);
    var first = findLayer(group, ["第 1 行"]);
    if (base.typename !== "ArtLayer" || base.kind !== LayerKind.SOLIDFILL ||
        header.typename !== "LayerSet" || first.typename !== "LayerSet" || header.layers.length < 2) {
        throw new Error("原生表格结构暂未识别：" + name + "，需要表格底、表头及逐行文字分组");
    }
    var columns = header.layers.length;
    for (var c = 1; c <= columns; c++) {
        if (findLayer(header, ["第 " + c + " 列"]).kind !== LayerKind.TEXT) {
            throw new Error("未定位原生表格表头文字：" + name + " / 第 " + c + " 列");
        }
    }
    for (var i = 0; i < group.layers.length; i++) {
        var row = group.layers[i];
        if (!/^第 \d+ 行$/.test(row.name)) continue;
        if (row.typename !== "LayerSet" || row.layers.length !== columns) throw new Error("原生表格各行列数不一致：" + name);
        for (c = 1; c <= columns; c++) {
            if (findLayer(row, ["第 " + c + " 列"]).kind !== LayerKind.TEXT) {
                throw new Error("未定位原生表格单元文字：" + name + " / " + row.name);
            }
        }
    }
    var bounds = box(base);
    if (bounds[2] - bounds[0] < 400 || bounds[3] - bounds[1] < 100) throw new Error("原生表格容器尺寸不足：" + name);
    return {group: group, base: base, columns: columns};
}

function classicTemplateProfile(doc) {
    var product = optionalClassicLayer(doc, "产品信息 拷贝 2");
    if (!product) return null;
    var info = findLayer(product, ["组 844"]);
    var color = findLayer(product, ["组 845"]);
    var columnLayout = optionalClassicLayer(product, "尺码快选") !== null;
    var size = findLayer(product, ["尺码"]);
    var editableSize = null, editableQuick = null;
    if (columnLayout) {
        findLayer(size, ["组 830", "组 1266", "组 1265"]);
        findLayer(product, ["试穿尺码"]);
    } else {
        var sizeRoot = findLayer(size, ["组 830"]);
        editableSize = classicEditableTable(sizeRoot, "03选尺码");
        editableQuick = classicEditableTable(size, "05尺码快选");
        if (!editableSize) findLayer(sizeRoot, ["03选尺码"]);
        if (!editableQuick) findLayer(size, ["05尺码快选"]);
    }
    var fields = ["名称", "货号", "材质", "颜色", "尺码"];
    for (var f = 0; f < fields.length; f++) {
        if (findLayer(info, [fields[f]]).kind !== LayerKind.TEXT) throw new Error("商品字段需要原生文字：" + fields[f]);
    }
    var model = findLayer(doc, ["模特"]);
    var frames = ["组 1113 拷贝 2", "组 1113 拷贝", "组 1113 拷贝 3"];
    for (var i = 0; i < frames.length; i++) {
        var bounds = box(findLayer(model, [frames[i], "矩形 1955"]));
        if (bounds[2] - bounds[0] < 200 || bounds[3] - bounds[1] < 300) throw new Error("模特图框尺寸不足：" + frames[i]);
    }
    findLayer(doc, ["品牌故事", "矩形 998"]);
    findLayer(doc, ["门店"]);
    return {product: product, info: info, colors: color, size: size, model: model,
            frames: frames, columnLayout: columnLayout, editableSize: editableSize, editableQuick: editableQuick,
            name: columnLayout ? "产品信息T" : "产品信息"};
}

function classicKeep(parent, names) {
    for (var i = parent.layers.length - 1; i >= 0; i--) {
        var keep = false;
        for (var j = 0; j < names.length; j++) if (parent.layers[i].name === names[j]) keep = true;
        if (!keep) parent.layers[i].remove();
    }
}

function wrapClassicMaterial(text, width, px) {
    var lines = [];
    var line = "";
    var used = 0;
    for (var i = 0; i < text.length; i++) {
        var character = text.charAt(i);
        var advance = /[\x00-\x7f]/.test(character) ? px * 0.58 : px;
        if (line && used + advance > width) {
            lines.push(line);
            line = "";
            used = 0;
        }
        line += character;
        used += advance;
    }
    if (line) lines.push(line);
    return lines;
}

function buildClassicInformation(doc, job, fonts, profile) {
    var fields = ["名称", "货号", "材质", "颜色", "尺码"];
    var rows = [];
    var right = 0;
    for (var i = 0; i < fields.length; i++) {
        var label = findLayer(profile.info, [fields[i]]);
        var bounds = box(label);
        rows.push({name: fields[i], top: bounds[1], bottom: bounds[3]});
    }
    for (i = 0; i < profile.info.artLayers.length; i++) {
        var value = profile.info.artLayers[i];
        if (value.kind === LayerKind.TEXT && value.visible) right = Math.max(right, box(value)[2]);
    }
    right = Math.min(750, right);
    classicKeep(profile.info, fields);
    var names = [];
    for (i = 0; i < job.products.length; i++) names.push(job.products[i].label);
    for (i = 0; i < rows.length; i++) {
        var row = rows[i];
        var text = row.name === "颜色" ? names.join("/") : job.info[row.name];
        if (row.name !== "材质") {
            var textPx = Math.min(26, Math.max(17, Math.floor((right - 180) / text.length)));
            workbenchText(profile.info, row.name + "值", text, right, row.bottom - 4,
                          right - 180, textPx, fonts, workbenchInk, Justification.RIGHT);
            continue;
        }
        var px = 24;
        var height = Math.max(54, rows[i + 1].top - row.top - 10);
        var lines = wrapClassicMaterial(text, right - 185, px);
        while (px > 12 && lines.length * px * 1.18 > height) {
            px--;
            lines = wrapClassicMaterial(text, right - 185, px);
        }
        var entry = workbenchText(profile.info, row.name + "值", lines.join("\r"), right,
                                   row.bottom - 4, right - 180, px, fonts, workbenchInk, Justification.RIGHT);
        entry.textItem.useAutoLeading = false;
        entry.textItem.leading = UnitValue(px * 1.15 * 72 / doc.resolution, "pt");
    }
    var details = optionalClassicLayer(profile.product, "组 1024");
    if (details) details.remove();
    var heading = null;
    var baseline = 0;
    for (i = 0; i < profile.colors.artLayers.length; i++) {
        var original = profile.colors.artLayers[i];
        if (original.kind === LayerKind.TEXT) {
            if (/STEP2/.test(original.textItem.contents)) heading = original.name;
            else baseline = Math.max(baseline, box(original)[3]);
        }
    }
    if (!heading || !baseline) throw new Error("缺少旧版母版的选色标题或色名文字");
    classicKeep(profile.colors, [heading]);
    var top = baseline - 292;
    for (i = profile.product.artLayers.length - 1; i >= 0; i--) {
        var old = profile.product.artLayers[i];
        var b = box(old);
        if (old.kind === LayerKind.SMARTOBJECT && b[1] >= top - 100 && b[1] < baseline) old.remove();
    }
    var step = 720 / job.products.length;
    for (i = 0; i < job.products.length; i++) {
        var center = 35 + step * (i + 0.5);
        var width = Math.min(210, step - 20);
        workbenchPicture(doc, profile.colors, job.products[i], "商品图 · " + job.products[i].label,
                         [center - width / 2, top, width, 230]);
        workbenchText(profile.colors, "色名 · " + job.products[i].label, job.products[i].label,
                      center, baseline - 3, step - 12, 26, fonts, workbenchInk, Justification.CENTER);
    }
}

function buildClassicTables(doc, job, fonts, profile) {
    var originalY = box(profile.size)[1];
    profile.size.remove();
    var quick = optionalClassicLayer(profile.product, "尺码快选");
    if (quick) quick.remove();
    var trial = optionalClassicLayer(profile.product, "试穿尺码");
    if (trial) trial.remove();
    var quickTitle = optionalClassicLayer(profile.product, "STEP3 尺码快选");
    if (quickTitle) quickTitle.remove();
    var root = profile.product.layerSets.add();
    root.name = "工作台尺码表格";
    var keys = ["03选尺码", "05尺码快选", "试穿报告"];
    var labels = ["选尺码", "尺码快选", "试穿报告"];
    var y = Math.max(1775, originalY);
    for (var i = 0; i < keys.length; i++) {
        var matrix = job.tables[keys[i]];
        if (!matrix) continue;
        var group = root.layerSets.add();
        group.name = keys[i] + "（可编辑）";
        var region = [29, y + 115, 760, y + 560];
        var spec = {key: keys[i], headerHeight: i === 2 ? 48 : 65, headerMin: 32,
                    rowHeight: 51, px: i === 2 ? 20 : 24, accent: i > 0};
        var widths = measurePantsDetailColumns(group, matrix, region, spec, fonts);
        var plan = planPantsDetailTable(matrix.length - 1, widths, 731, 445, spec);
        rectangle(doc, group, "模块底色", 10, y, 770, plan.height + 155, [247, 247, 247], 14);
        workbenchText(group, "模块标题", labels[i], 48, y + 65, 450, 38, fonts, workbenchGreen);
        workbenchText(group, "单位", i === 0 ? "cm" : "cm / kg", 742, y + 65, 250, 23, fonts,
                      workbenchInk, Justification.RIGHT);
        var base = rectangle(doc, group, "原母版圆角表底", region[0], region[1], 731, 445, [255, 255, 255], 12);
        drawPantsDetailTable(doc, group, base, matrix, region, plan, spec, fonts);
        y += plan.height + 190;
    }
    return y;
}

function buildClassicModels(doc, job, profile, after) {
    var model = profile.model;
    var keep = profile.frames.slice();
    for (var i = 0; i < model.artLayers.length; i++) {
        var layer = model.artLayers[i];
        if (layer.kind === LayerKind.TEXT && /模特展示/.test(layer.textItem.contents)) keep.push(layer.name);
    }
    classicKeep(model, keep);
    var originalTop = box(model)[1];
    for (i = 0; i < profile.frames.length; i++) {
        var frameGroup = findLayer(model, [profile.frames[i]]);
        classicKeep(frameGroup, ["矩形 1955"]);
        if (i < job.scenes.length) {
            workbenchPicture(doc, frameGroup, job.scenes[i], "模特图 " + (i + 1), null,
                             findLayer(frameGroup, ["矩形 1955"]));
        } else frameGroup.remove();
    }
    if (!job.scenes.length) {
        model.remove();
        return after;
    }
    if (job.scenes.length === 4) {
        var last = findLayer(model, [profile.frames[2], "矩形 1955"]);
        var b = box(last);
        var extra = model.layerSets.add();
        extra.name = "工作台第四模特图";
        var mask = rectangle(doc, extra, "照片框", b[0], b[3] + 80, b[2] - b[0], b[3] - b[1], [240, 245, 241], 14);
        workbenchPicture(doc, extra, job.scenes[3], "模特图 4", null, mask);
    }
    model.translate(UnitValue(0, "px"), UnitValue(after + 70 - originalTop, "px"));
    return box(model)[3] + 70;
}

function cleanClassicBrand(group) {
    for (var i = group.layers.length - 1; i >= 0; i--) {
        var layer = group.layers[i];
        if (layer.typename === "LayerSet") {
            cleanClassicBrand(layer);
            continue;
        }
        var b = box(layer);
        if (((layer.kind === LayerKind.SMARTOBJECT || layer.kind === LayerKind.NORMAL) &&
            (b[2] - b[0] > 100 || b[3] - b[1] > 100)) || layer.kind === LayerKind.CURVES ||
            layer.kind === LayerKind.HUESATURATION) layer.remove();
    }
}

function buildClassicWorkbench(doc, job, fonts, profile) {
    buildClassicInformation(doc, job, fonts, profile);
    var after = buildClassicTables(doc, job, fonts, profile);
    after = buildClassicModels(doc, job, profile, after);
    var quality = optionalClassicLayer(doc, "质检 拷贝 2");
    if (quality) quality.remove();
    var brand = findLayer(doc, ["品牌故事"]);
    if (job.scenes.length) {
        cleanClassicBrand(brand);
        var picture = workbenchPicture(doc, brand, job.scenes[0], "工作台品牌场景", null, findLayer(brand, ["矩形 998"]));
        for (var i = brand.artLayers.length - 1; i >= 0; i--) {
            var layer = brand.artLayers[i];
            if (layer.kind === LayerKind.TEXT) layer.move(picture, ElementPlacement.PLACEBEFORE);
        }
        brand.translate(UnitValue(0, "px"), UnitValue(after - box(brand)[1], "px"));
        after = box(brand)[3] + 60;
    } else {
        brand.remove();
    }
    var footer = findLayer(doc, ["门店"]);
    footer.translate(UnitValue(0, "px"), UnitValue(after - box(footer)[1], "px"));
    var height = Math.ceil(box(footer)[3] + 30);
    doc.resizeCanvas(UnitValue(790, "px"), UnitValue(height, "px"), AnchorPosition.TOPCENTER);
    return height;
}

function verifyClassicWorkbench(doc, job) {
    var product = findLayer(doc, ["产品信息 拷贝 2"]);
    var info = findLayer(product, ["组 844"]);
    for (var field in job.info) {
        var layer = findLayer(info, [field + "值"]);
        if (layer.kind !== LayerKind.TEXT || layer.textItem.contents.replace(/\r/g, "") !== job.info[field]) throw new Error("旧版商品字段重开校验失败：" + field);
        var bounds = box(layer);
        if (bounds[0] < 0 || bounds[2] > 790) throw new Error("旧版商品字段超出画布：" + field);
    }
    var tables = findLayer(product, ["工作台尺码表格"]);
    for (var name in job.tables) {
        var table = findLayer(tables, [name + "（可编辑）"]);
        var matrix = job.tables[name];
        for (var r = 0; r < matrix.length; r++) {
            var row = findLayer(table, [r === 0 ? "表头" : "第 " + r + " 行"]);
            for (var c = 0; c < matrix[r].length; c++) {
                layer = findLayer(row, ["第 " + (c + 1) + " 列"]);
                if (layer.kind !== LayerKind.TEXT || layer.textItem.contents !== (matrix[r][c] || " ")) {
                    throw new Error("旧版表格重开校验失败：" + name);
                }
            }
        }
    }
    var count = verifyEmbedded(findLayer(product, ["组 845"]), /^商品图 · /);
    if (job.scenes.length) count += verifyEmbedded(findLayer(doc, ["模特"]), /^模特图 [1-4]$/);
    if (count !== job.products.length + job.scenes.length) throw new Error("旧版图片嵌入数量不符");
}
