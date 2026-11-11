/* Source-layer bindings shared by export and the desktop preview. */
function manifestString(value) {
    return '"' + String(value).replace(/[\\"\u0000-\u001f]/g, function (character) {
        if (character === "\\") return "\\\\";
        if (character === '"') return '\\"';
        var code = character.charCodeAt(0).toString(16);
        return "\\u" + ("0000" + code).slice(-4);
    }) + '"';
}

function manifestJson(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value === "string") return manifestString(value);
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    var parts = [];
    var i;
    if (value instanceof Array) {
        for (i = 0; i < value.length; i++) parts.push(manifestJson(value[i]));
        return "[" + parts.join(",") + "]";
    }
    for (var key in value) {
        if (value.hasOwnProperty(key)) parts.push(manifestString(key) + ":" + manifestJson(value[key]));
    }
    return "{" + parts.join(",") + "}";
}

function manifestWrite(path, value) {
    var file = new File(path);
    file.encoding = "UTF8";
    if (!file.open("w")) throw new Error("无法写入母版布局记录");
    file.write(manifestJson(value));
    file.close();
}

function manifestPath(layer) {
    var result = [layer.name];
    var parent = layer.parent;
    while (parent.typename !== "Document") {
        result.unshift(parent.name);
        parent = parent.parent;
    }
    return result;
}

function manifestRect(layer) {
    var bounds = box(layer);
    return [bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]];
}

function manifestStyle(layer, doc) {
    var result = {font: "", size_px: 24, color: [33, 51, 48], align: "left"};
    if (layer.kind !== LayerKind.TEXT) return result;
    try {
        var item = layer.textItem;
        result.font = item.font;
        result.size_px = item.size.as("pt") * doc.resolution / 72;
        result.color = [item.color.rgb.red, item.color.rgb.green, item.color.rgb.blue];
        result.align = item.justification === Justification.RIGHT ? "right" : item.justification === Justification.CENTER ? "center" : "left";
    } catch (error) {
        throw new Error("读取标题样式失败 " + manifestPath(layer).join(" / ") + "，" + error.message);
    }
    return result;
}

function manifestPrefix(path, parent) {
    if (path.length < parent.length) return false;
    for (var i = 0; i < parent.length; i++) if (path[i] !== parent[i]) return false;
    return true;
}

function manifestExcluded(path, exclusions) {
    for (var i = 0; i < exclusions.length; i++) if (manifestPrefix(path, exclusions[i])) return true;
    return false;
}

function manifestTitles(parent, exclusions, doc) {
    var titles = [];
    if (!parent) throw new Error("读取固定文字时缺少实际图层容器");
    if (parent.typename !== "LayerSet" && parent.typename !== "Document") return titles;
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        var path = manifestPath(layer);
        if (manifestExcluded(path, exclusions)) continue;
        if (layer.typename === "LayerSet") titles = titles.concat(manifestTitles(layer, exclusions, doc));
        else if (layer.kind === LayerKind.TEXT && layer.visible) {
            var contents = "";
            try {
                contents = layer.textItem.contents;
                titles.push({path: path, text: contents, rect: manifestRect(layer), style: manifestStyle(layer, doc)});
            } catch (error) {
                if (/STEP|^S[1-9]$|选尺码|尺码快选|试穿报告|选颜色|挑颜色|看信息/.test(contents)) {
                    throw new Error("读取模块标题失败 " + path.join(" / ") + "，" + error.message);
                }
                titles.push({path: path, text: contents, rect: manifestRect(layer), static_only: true,
                             unreadable_style: true, style: null});
            }
        }
    }
    return titles;
}

function manifestRemovals(parent, preserved) {
    var result = [];
    if (parent.typename !== "LayerSet" && parent.typename !== "Document") {
        var own = manifestPath(parent);
        return manifestExcluded(own, preserved) ? [] : [own];
    }
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        var path = manifestPath(layer);
        var contains = false;
        var equal = false;
        for (var j = 0; j < preserved.length; j++) {
            if (manifestPrefix(preserved[j], path)) contains = true;
            if (manifestPrefix(path, preserved[j])) equal = true;
        }
        if (equal) continue;
        if (contains && layer.typename === "LayerSet") result = result.concat(manifestRemovals(layer, preserved));
        else if (!contains) result.push(path);
    }
    return result;
}

function manifestUnion(rectangles) {
    var left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (var i = 0; i < rectangles.length; i++) {
        var r = rectangles[i];
        left = Math.min(left, r[0]); top = Math.min(top, r[1]);
        right = Math.max(right, r[0] + r[2]); bottom = Math.max(bottom, r[1] + r[3]);
    }
    return [left, top, right - left, bottom - top];
}

function manifestStaticRects(parent, exclusions) {
    var rectangles = [];
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (!layer.visible || manifestExcluded(manifestPath(layer), exclusions)) continue;
        if (layer.typename === "LayerSet") rectangles = rectangles.concat(manifestStaticRects(layer, exclusions));
        else {
            var r = manifestRect(layer);
            if (r[2] > 0 && r[3] > 0) rectangles.push(r);
        }
    }
    return rectangles;
}

function manifestPageRect(rect) {
    var left = Math.max(0, rect[0]);
    var right = Math.min(790, rect[0] + rect[2]);
    return [left, Math.max(0, rect[1]), Math.max(1, right - left), rect[3]];
}

function manifestModule(doc, role, layer, rect, exclusions, extraPaths) {
    if (!layer) throw new Error("模块缺少实际图层：" + role);
    var titles = manifestTitles(layer, exclusions || [], doc);
    var paths = [manifestPath(layer)];
    extraPaths = extraPaths || [];
    for (var i = 0; i < extraPaths.length; i++) {
        var extra = findLayer(doc, extraPaths[i]);
        paths.push(extraPaths[i]);
        if (extra.kind === LayerKind.TEXT) titles.push({path: extraPaths[i], text: extra.textItem.contents,
            rect: manifestRect(extra), style: manifestStyle(extra, doc)});
    }
    return {role: role, path: paths[0], move_paths: paths, rect: rect || manifestRect(layer), titles: titles};
}

function manifestFieldBindings(doc, info) {
    var names = ["名称", "货号", "材质", "颜色", "尺码"];
    var labels = [];
    var values = [];
    var fields = {};
    for (var i = 0; i < names.length; i++) {
        var label = findLayer(info, [names[i]]);
        labels.push({name: names[i], layer: label, rect: manifestRect(label)});
    }
    for (i = 0; i < info.artLayers.length; i++) {
        var item = info.artLayers[i];
        if (item.kind !== LayerKind.TEXT) continue;
        var isLabel = false;
        for (var j = 0; j < names.length; j++) if (item.name === names[j]) isLabel = true;
        if (!isLabel) values.push(item);
    }
    for (i = 0; i < labels.length; i++) {
        var row = labels[i];
        var paths = [], rectangles = [], original = [], sample = null;
        for (j = 0; j < values.length; j++) {
            var r = manifestRect(values[j]);
            if (r[0] <= row.rect[0] + row.rect[2] + 10) continue;
            var nearest = 0, distance = Infinity;
            for (var k = 0; k < labels.length; k++) {
                var delta = Math.abs(r[1] - labels[k].rect[1]);
                if (delta < distance) { distance = delta; nearest = k; }
            }
            if (nearest !== i) continue;
            paths.push(manifestPath(values[j]));
            if (values[j].visible) {
                rectangles.push(r); original.push(values[j].textItem.contents);
                if (!sample) sample = values[j];
            }
        }
        if (!paths.length || !sample) throw new Error("未能唯一识别母版的商品字段：" + row.name);
        var union = manifestUnion(rectangles);
        var rightEdge = Math.min(750, union[0] + union[2]);
        var nextTop = i + 1 < labels.length ? labels[i + 1].rect[1] : row.rect[1] + 58;
        var sourceStyle = manifestStyle(sample, doc);
        var targetStyle = manifestStyle(sample, doc);
        targetStyle.align = "right";
        fields[row.name] = {paths: paths, rect: [Math.max(180, row.rect[0] + row.rect[2] + 30), row.rect[1],
            rightEdge - Math.max(180, row.rect[0] + row.rect[2] + 30), Math.max(38, nextTop - row.rect[1] - 8)],
            original_rect: union, label_path: manifestPath(row.layer), label_rect: row.rect,
            original_text: original.join(""), original_style: sourceStyle, style: targetStyle};
    }
    return fields;
}

function manifestColorBindings(doc, container, product, fields, fallback) {
    var textLayers = [];
    for (var i = 0; i < container.artLayers.length; i++) {
        var text = container.artLayers[i];
        if (text.kind === LayerKind.TEXT && text.visible) textLayers.push(text);
    }
    textLayers.sort(function (a, b) { return box(a)[1] - box(b)[1]; });
    var heading = textLayers.length ? textLayers[0] : null;
    var labels = textLayers.slice(1);
    var images = [], allImages = [];
    var candidates = product === container ? container.artLayers : product.artLayers;
    for (i = 0; i < candidates.length; i++) {
        var layer = candidates[i];
        var r = manifestRect(layer);
        if (layer.kind === LayerKind.SMARTOBJECT && r[2] >= 100 && r[3] >= 100) {
            allImages.push(layer);
            if (layer.visible) images.push(layer);
        }
    }
    if (labels.length && images.length !== labels.length) {
        throw new Error("颜色原图与色名无法唯一配对，请把每张色图和色名放到同一选色模块。");
    }
    labels.sort(function (a, b) { return box(a)[0] - box(b)[0]; });
    images.sort(function (a, b) { return box(a)[0] - box(b)[0]; });
    var slots = [], paths = [];
    for (i = 0; i < labels.length; i++) {
        slots.push({image_path: manifestPath(images[i]), label_path: manifestPath(labels[i]),
            rect: manifestRect(images[i]), label_rect: manifestRect(labels[i]),
            text: labels[i].textItem.contents, style: manifestStyle(labels[i], doc)});
        paths.push(manifestPath(images[i])); paths.push(manifestPath(labels[i]));
    }
    for (i = 0; i < allImages.length; i++) {
        var candidate = manifestPath(allImages[i]);
        if (!manifestExcluded(candidate, paths)) paths.push(candidate);
    }
    var rect = fallback.rect;
    return {rect: rect, slots: slots, original_count: slots.length, columns: slots.length || 4,
        data_paths: paths, heading_path: heading ? manifestPath(heading) : null,
        prototype: {image_rect: slots.length ? slots[0].rect : fallback.image_rect,
            label_rect: slots.length ? slots[0].label_rect : fallback.label_rect,
            style: slots.length ? slots[0].style : {font: "FZLTZHK--GBK1-0", size_px: 27, color: [33, 51, 48], align: "center"}}};
}

function manifestDirectTitle(parent, expression) {
    var result = null;
    for (var i = 0; i < parent.artLayers.length; i++) {
        var layer = parent.artLayers[i];
        if (layer.kind === LayerKind.TEXT && layer.visible && expression.test(layer.textItem.contents)) {
            if (result) throw new Error("母版标题存在多个候选，请明确模块分组：" + layer.textItem.contents);
            result = layer;
        }
    }
    return result;
}

function manifestSemanticSection(root, expression, preferredName) {
    if (!root) throw new Error("母版缺少尺码模块根分组");
    if (preferredName) {
        var known = optionalClassicLayer(root, preferredName);
        if (known && known.typename === "LayerSet") return known;
    }
    var result = null;
    for (var i = 0; i < root.layers.length; i++) {
        var section = root.layers[i];
        if (!section || section.typename !== "LayerSet") continue;
        var texts = manifestTitles(section, [], app.activeDocument);
        var matched = false;
        for (var j = 0; j < texts.length; j++) if (expression.test(texts[j].text)) matched = true;
        if (matched) {
            if (result) throw new Error("无法唯一识别尺码模块，请保留独立模块分组");
            result = section;
        }
    }
    if (!result) throw new Error("母版缺少对应尺码标题与容器");
    return result;
}

function manifestImageData(parent, role, photoContainers) {
    var entries = [];
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (layer.typename === "LayerSet") entries = entries.concat(manifestImageData(layer, role, photoContainers));
        else {
            var r = manifestRect(layer);
            var belongsToPhoto = false;
            if (photoContainers) belongsToPhoto = manifestExcluded(manifestPath(layer), photoContainers);
            var adjustment = layer.kind === LayerKind.CURVES || layer.kind === LayerKind.HUESATURATION ||
                layer.kind === LayerKind.LEVELS || layer.kind === LayerKind.COLORBALANCE ||
                layer.kind === LayerKind.SELECTIVECOLOR || layer.kind === LayerKind.BRIGHTNESSCONTRAST ||
                layer.kind === LayerKind.VIBRANCE;
            var isImage = false;
            if (layer.kind === LayerKind.SMARTOBJECT) isImage = true;
            if (layer.kind === LayerKind.NORMAL) isImage = true;
            var include = false;
            if (isImage) {
                if (belongsToPhoto) include = true;
                if (r[2] > 100) {
                    if (r[3] > 100) include = true;
                }
            }
            if (adjustment) include = true;
            if (include) {
                entries.push({path: manifestPath(layer), role: role, kind: adjustment ? "adjustment" : "image"});
            }
        }
    }
    return entries;
}

function manifestClassicSceneImages(profile) {
    var containers = [];
    for (var i = 0; i < profile.frames.length; i++) containers.push(manifestPath(findLayer(profile.model, [profile.frames[i]])));
    return manifestImageData(profile.model, "scenes", containers);
}

function manifestTable(doc, role, key, root, rect, basePath, dataPaths, style, moduleRect, extraPaths) {
    var module = manifestModule(doc, role, root, moduleRect, dataPaths, extraPaths);
    module.table = {key: key, rect: rect, base_path: basePath, data_paths: dataPaths, style: style,
                    parent_path: root.typename === "LayerSet" ? manifestPath(root) : manifestPath(root.parent)};
    return module;
}

function manifestEditableTableData(group) {
    var paths = [];
    for (var i = 0; i < group.layers.length; i++) {
        var layer = group.layers[i];
        if (/^(表头|第 \d+ 行|表头底色|表头下沿|交替行底色 \d+|行标底色(?: \d+)?|横线 \d+|竖线 \d+|行间隔线 \d+)$/.test(layer.name)) {
            paths.push(manifestPath(layer));
        }
    }
    return paths;
}

function manifestEditableTableBackgrounds(group) {
    var paths = [];
    var names = ["面板底色", "内容底色", "表格衬底"];
    for (var i = 0; i < names.length; i++) {
        var layer = optionalClassicLayer(group, names[i]);
        if (layer) paths.push(manifestPath(layer));
    }
    return paths;
}

function manifestContainsName(names, value) {
    for (var i = 0; i < names.length; i++) if (names[i] === value) return true;
    return false;
}

function manifestMeasurementName(name) {
    if (manifestContainsName(["尺码示意图", "尺寸示意图", "量体示意图", "测量示意图"], name)) return true;
    var prefixes = ["尺码", "尺寸", "服装", "服饰"];
    for (var i = 0; i < prefixes.length; i++) {
        if (name.indexOf(prefixes[i]) === 0) {
            name = name.substring(prefixes[i].length);
            break;
        }
    }
    return manifestContainsName([
        "测量图", "测量示意图", "测量方式图", "测量方式示意图", "测量方法图", "测量方法示意图",
        "量体图", "量体示意图", "量体方式图", "量体方式示意图", "量体方法图", "量体方法示意图"
    ], name);
}

function inspectManifestMeasurement(layer, evidence, dimension, depth) {
    if (!layer.visible || evidence.invalid) return;
    if (layer.typename === "LayerSet") {
        if (!depth) return;
        var children = layer.layers;
        for (var i = 0, count = children.length; i < count && !evidence.invalid; i++) {
            inspectManifestMeasurement(children[i], evidence, dimension, depth - 1);
        }
        return;
    }
    var kind = layer.kind;
    if (kind === LayerKind.TEXT) {
        var text = "";
        try { text = layer.textItem.contents.replace(/\s/g, ""); } catch (error) {}
        if (manifestContainsName(dimension, text)) evidence.labels++;
        else evidence.invalid = true;
    } else if (kind === LayerKind.NORMAL || kind === LayerKind.SMARTOBJECT) {
        evidence.artwork = true;
    }
}

function bindManifestMeasurement(doc, profile, classic, reportStage) {
    var size = manifestFindModule(profile, "size_table");
    if (!size) return;
    if (reportStage) reportStage("识别量体图 · 定位尺码分组");
    var section = findLayer(doc, size.path);
    var parents = [{layer: section, path: size.path}];
    if (classic) {
        parents.push({layer: classic.size, path: size.path.slice(0, -1)});
        var column = optionalClassicLayer(section, "组 1266");
        if (column && column.typename === "LayerSet" && column.visible) {
            parents.push({layer: column, path: size.path.concat(["组 1266"])});
        }
    }
    var candidates = [];
    var dimension = ["肩宽", "衣长", "袖长", "胸围", "摆围", "下摆", "腰围", "臀围", "裤长", "裤口",
                     "领围", "袖口", "前浪", "后浪", "裆长", "脚口", "裙长", "身长", "裆深", "内长", "腿围", "大腿围"];
    // Read only direct children of known size-section containers. Unrelated
    // size table rows, model pictures and nested product graphics are not scanned.
    for (var p = 0; p < parents.length; p++) {
        var children = parents[p].layer.layers;
        var groupPath = parents[p].path;
        for (var i = 0, count = children.length; i < count; i++) {
            if (reportStage) reportStage("识别量体图 · 核对尺码区图层 " + (i + 1) + "/" + count);
            var candidate = children[i];
            var label = candidate.name;
            var name = label.replace(/\s/g, "");
            var explicit = manifestMeasurementName(name);
            if (!explicit && !(classic && name === "组1264")) continue;
            var candidatePath = groupPath.concat([label]);
            if (!candidate.visible || (candidate.typename === "ArtLayer" && candidate.grouped) ||
                manifestExcluded(candidatePath, size.table.data_paths)) continue;
            var evidence = {artwork: false, labels: 0, invalid: false};
            inspectManifestMeasurement(candidate, evidence, dimension, 4);
            var valid = evidence.artwork || (explicit && candidate.typename === "ArtLayer" &&
                                             candidate.kind === LayerKind.SOLIDFILL);
            if (!evidence.invalid && valid && (explicit || evidence.labels >= 2)) {
                candidates.push({layer: candidate, path: candidatePath});
            }
        }
    }
    if (candidates.length !== 1) return;
    var layer = candidates[0].layer;
    var path = candidates[0].path;
    if (!manifestVisiblePath(doc, path)) return;
    var bounds = box(layer);
    var x = Math.floor(bounds[0]), y = Math.floor(bounds[1]);
    var right = Math.ceil(bounds[2]), bottom = Math.ceil(bounds[3]);
    var table = size.table.rect;
    var after = y >= table[1] + table[3] - 1;
    // Some column templates deliberately overlap the unoccupied edge of the
    // old table backing by a few pixels. Reserve that edge in the new grid.
    var beside = right <= table[0] + 20 || x >= table[0] + table[2] - 20;
    if ((!after && !beside) || right - x < 60 || bottom - y < 60 || x < 0 ||
        right > profile.canvas.width || y < size.rect[1] || bottom > profile.canvas.height) return;
    var nextTop = profile.canvas.height;
    for (var i = 0; i < profile.modules.length; i++) {
        var other = profile.modules[i];
        if (other.rect[1] > size.rect[1]) nextTop = Math.min(nextTop, other.rect[1]);
    }
    if (bottom > nextTop) return;
    for (i = profile.omitted_paths.length - 1; i >= 0; i--) {
        var omission = profile.omitted_paths[i];
        if (manifestPrefix(path, omission) && omission.length === path.length) profile.omitted_paths.splice(i, 1);
        else if (manifestPrefix(path, omission)) return;
    }
    for (i = size.titles.length - 1; i >= 0; i--) {
        if (manifestPrefix(size.titles[i].path, path)) size.titles.splice(i, 1);
    }
    size.rect[3] = Math.max(size.rect[3], bottom - size.rect[1]);
    profile.view_slots.measurement = {id: "measurement", role: "size_table", after_table: after, beside_table: !after && beside,
                                      path: path, rect: [x, y, right - x, bottom - y]};
}

function bindManifestSizeNote(doc, profile) {
    var size = manifestFindModule(profile, "size_table");
    if (!size) return;
    var lines = [];
    var nextTop = profile.canvas.height;
    for (var i = 0; i < profile.modules.length; i++) {
        var other = profile.modules[i];
        if (other.rect[1] > size.rect[1]) nextTop = Math.min(nextTop, other.rect[1]);
    }
    for (i = 0; i < size.titles.length; i++) {
        var title = size.titles[i];
        if (!title.style || title.static_only || title.rect[1] < size.rect[1] ||
            title.rect[1] + title.rect[3] > nextTop) continue;
        var text = title.text.replace(/\r\n?/g, "\n").replace(/^\s+|\s+$/g, "");
        if (!/^(?:(?:注(?:意)?|备注|尺码备注)\s*[:：].*(?:尺码|尺寸|测量|误差)|(?:所给|以上|表中|所有)?\s*尺寸均为全尺寸)/.test(text)) continue;
        if (manifestExcluded(title.path, profile.omitted_paths) || !manifestVisiblePath(doc, title.path)) continue;
        lines.push({path: title.path, rect: title.rect, style: title.style, text: text});
    }
    if (!lines.length) return;
    lines.sort(function (a, b) { return a.rect[1] - b.rect[1]; });
    var rects = [], texts = [];
    for (i = 0; i < lines.length; i++) {
        rects.push(lines[i].rect);
        texts.push(lines[i].text);
    }
    var rect = manifestUnion(rects);
    var after = rect[1] >= size.table.rect[1] + size.table.rect[3] - 8;
    size.rect[3] = Math.max(size.rect[3], rect[1] + rect[3] - size.rect[1]);
    rect[2] = Math.max(rect[2], size.rect[0] + size.rect[2] - rect[0] - 20);
    profile.size_note = {text: texts.join("\n"), lines: lines, rect: rect,
                         style: lines[0].style, after_table: after};
}

function hideManifestSizeNote(doc, profile) {
    if (!profile.size_note) return;
    var lines = profile.size_note.lines;
    for (var i = 0; i < lines.length; i++) findLayer(doc, lines[i].path).visible = false;
}

function manifestProductAttributes(doc, group, panel) {
    if (!group || !group.visible || group.typename !== "LayerSet") return null;
    var names = ["宽松", "修身", "紧身"];
    var shapeNames = ["符号 拷贝 4", "矩形 802"];
    var symbol = optionalClassicLayer(group, shapeNames[0]);
    var pill = optionalClassicLayer(group, shapeNames[1]);
    if (!symbol || !pill || !symbol.visible || !pill.visible) return null;
    var pillBox = box(pill), symbolBox = box(symbol);
    var center = (pillBox[0] + pillBox[2]) / 2;
    var fit = {options: [], shapes: shapeNames, pill_left: pillBox[0], default_value: "", active: null, inactive: null};
    var rects = [manifestRect(group)];
    var closest = Infinity;
    for (var i = 0; i < names.length; i++) {
        var layer = optionalClassicLayer(group, names[i]);
        if (!layer || !layer.visible || layer.kind !== LayerKind.TEXT || layer.textItem.contents !== names[i]) return null;
        var bounds = box(layer);
        var textCenter = (bounds[0] + bounds[2]) / 2;
        var offset = textCenter - center;
        var dx = Math.max(panel[0] + 5 - symbolBox[0],
                          Math.min(offset, panel[0] + panel[2] - 5 - pillBox[2]));
        var color = manifestStyle(layer, doc).color;
        var option = {value: names[i], dx: dx, text_dx: dx - offset, color: color};
        fit.options.push(option);
        if (Math.abs(offset) < closest) {
            closest = Math.abs(offset);
            fit.default_value = names[i];
            fit.active = color;
        }
        rects.push([symbolBox[0] + dx, Math.min(symbolBox[1], pillBox[1]), pillBox[2] - symbolBox[0],
                    Math.max(symbolBox[3], pillBox[3]) - Math.min(symbolBox[1], pillBox[1])]);
    }
    for (i = 0; i < fit.options.length; i++) {
        option = fit.options[i];
        if (option.value !== fit.default_value) fit.inactive = option.color;
        else option.dx = option.text_dx = 0;
    }
    var labels = ["触感", "厚度", "弹性"], fields = {};
    for (i = 0; i < group.layerSets.length; i++) {
        var chip = group.layerSets[i], label = null, value = null, badge = null;
        for (var j = 0; j < chip.artLayers.length; j++) {
            layer = chip.artLayers[j];
            if (!layer.visible) continue;
            if (layer.kind === LayerKind.SMARTOBJECT) badge = layer;
            if (layer.kind !== LayerKind.TEXT) continue;
            var contents = layer.textItem.contents;
            if (/^(触感|厚度|弹性)$/.test(contents)) label = contents;
            else value = layer;
        }
        if (!label || !value || !badge) continue;
        var area = manifestRect(badge);
        var style = manifestStyle(value, doc);
        style.align = "center";
        fields[label] = {path: [chip.name, value.name], text: value.textItem.contents, style: style,
                         rect: [area[0] + 6, manifestRect(value)[1] - 4, area[2] - 12, area[3]]};
    }
    for (i = 0; i < labels.length; i++) if (!fields[labels[i]]) return null;
    var rect = manifestUnion(rects);
    var left = Math.floor(rect[0]) - 2, top = Math.floor(rect[1]) - 2;
    return {path: manifestPath(group), fit: fit, fields: fields,
            rect: [left, top, Math.ceil(rect[0] + rect[2]) + 2 - left,
                   Math.ceil(rect[1] + rect[3]) + 2 - top]};
}

function setManifestFit(group, fit, value) {
    if (value === fit.default_value) return;
    for (var i = 0; i < fit.options.length; i++) {
        var option = fit.options[i];
        var layer = findLayer(group, [option.value]);
        var selected = option.value === value;
        layer.textItem.color = rgb(selected ? fit.active : fit.inactive);
        if (!selected) continue;
        if (option.text_dx) layer.translate(UnitValue(option.text_dx, "px"), UnitValue(0, "px"));
        for (var j = 0; j < fit.shapes.length; j++) {
            findLayer(group, [fit.shapes[j]]).translate(UnitValue(option.dx, "px"), UnitValue(0, "px"));
        }
    }
}

function exportManifestProductAttributes(doc, profile, folder) {
    var attributes = profile.product_attributes;
    if (!attributes) return;
    var group = findLayer(doc, attributes.path), frame = attributes.rect;
    var sourceBounds = box(group);
    for (var i = 0; i < attributes.fit.options.length; i++) {
        var option = attributes.fit.options[i];
        var isolated = app.documents.add(UnitValue(frame[2], "px"), UnitValue(frame[3], "px"),
            doc.resolution, "STEP1 属性预览", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
        try {
            app.activeDocument = doc;
            var copy = group.duplicate(isolated, ElementPlacement.PLACEATBEGINNING);
            app.activeDocument = isolated;
            var actual = box(copy);
            copy.translate(UnitValue(sourceBounds[0] - frame[0] - actual[0], "px"),
                           UnitValue(sourceBounds[1] - frame[1] - actual[1], "px"));
            setManifestFit(copy, attributes.fit, option.value);
            for (var field in attributes.fields) findLayer(copy, attributes.fields[field].path).visible = false;
            option.image = folder + "/step1-attributes-" + i + ".png";
            isolated.saveAs(new File(option.image), new PNGSaveOptions(), true, Extension.LOWERCASE);
        } finally {
            isolated.close(SaveOptions.DONOTSAVECHANGES);
            app.activeDocument = doc;
        }
    }
}

function reviewManifestProductAttributes(spec) {
    var units = app.preferences.rulerUnits, dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc;
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        doc = app.open(new File(spec.source));
        var classic = classicTemplateProfile(doc);
        if (!classic) throw new Error("找不到旧版商品信息模块");
        var panel = manifestRect(findLayer(classic.product, ["矩形 948 拷贝"]));
        var group = optionalClassicLayer(classic.product, "组 1024");
        var attributes = manifestProductAttributes(doc, group, panel);
        exportManifestProductAttributes(doc, {product_attributes: attributes}, spec.assetsFolder);
        manifestWrite(spec.output, attributes);
    } finally {
        if (doc) doc.close(SaveOptions.DONOTSAVECHANGES);
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) { try { app.activeDocument = prior; } catch (priorError) {} }
    }
}

function manifestClassic(doc, profile, reportStage) {
    var result = {version: 1, family: "classic", canvas: {width: 790, height: doc.height.as("px")},
        modules: [], view_slots: {}, original_images: [], omitted_paths: [], stretch_paths: []};
    if (reportStage) reportStage("读取商品信息和选颜色布局");
    result.fields = manifestFieldBindings(doc, profile.info);
    var fieldPaths = [];
    for (var name in result.fields) fieldPaths = fieldPaths.concat(result.fields[name].paths);
    var productPath = manifestPath(profile.product);
    var infoTop = manifestDirectTitle(profile.product, /看信息|产品信息|商品信息/);
    if (!infoTop) throw new Error("母版缺少商品信息模块标题");
    var secondLine = findLayer(profile.product, ["直线 1512 拷贝"]);
    var colorTop = box(secondLine)[1];
    var base = findLayer(profile.product, ["矩形 948 拷贝"]);
    var panel = manifestRect(base);
    result.modules.push(manifestModule(doc, "product", profile.info,
        [panel[0], panel[1], panel[2], colorTop - panel[1]], fieldPaths, [manifestPath(infoTop)]));
    var colorRect = [panel[0], colorTop, panel[2], panel[1] + panel[3] - colorTop];
    result.colors = manifestColorBindings(doc, profile.colors, profile.product, result.fields,
        {rect: colorRect, image_rect: [65, colorTop + 150, 210, 230], label_rect: [65, colorTop + 420, 210, 30]});
    result.modules.push(manifestModule(doc, "colors", profile.colors, colorRect, result.colors.data_paths,
                                      [manifestPath(secondLine)]));
    result.stretch_paths.push({path: manifestPath(base), role: "colors"});
    var optional = optionalClassicLayer(profile.product, "组 1024");
    result.product_attributes = manifestProductAttributes(doc, optional, panel);
    if (result.product_attributes) result.modules[0].move_paths.push(result.product_attributes.path);
    if (optional) result.omitted_paths.push(manifestPath(optional));
    optional = optionalClassicLayer(doc, "质检 拷贝 2");
    if (optional) result.omitted_paths.push(manifestPath(optional));
    if (reportStage) reportStage("读取尺码表布局");
    var sourceSize = findLayer(profile.size, ["组 830"]);
    var sizeBody, sizeRect, sizeData, sizeBasePath = null;
    if (profile.columnLayout) {
        sizeBody = findLayer(sourceSize, ["组 1266", "组 1265"]);
        var sizeHeader = findLayer(sizeBody, ["矩形 1602 拷贝 4"]);
        var sh = manifestRect(sizeHeader);
        sizeRect = [Math.max(25, sh[0] - 8), sh[1], sh[2] + 8, 420];
        sizeData = [manifestPath(sizeBody)];
        var diagram = optionalClassicLayer(findLayer(sourceSize, ["组 1266"]), "组 1264");
        if (diagram) result.omitted_paths.push(manifestPath(diagram));
        diagram = optionalClassicLayer(sourceSize, "组 1264");
        if (diagram) result.omitted_paths.push(manifestPath(diagram));
    } else if (profile.editableSize) {
        sizeBody = profile.editableSize.group;
        sizeRect = manifestRect(profile.editableSize.base);
        sizeBasePath = manifestPath(profile.editableSize.base);
        sizeData = manifestEditableTableData(sizeBody);
        var hiddenLegacyTable = optionalClassicLayer(sourceSize, "组 1041");
        if (hiddenLegacyTable && !hiddenLegacyTable.visible) result.omitted_paths.push(manifestPath(hiddenLegacyTable));
        diagram = optionalClassicLayer(profile.size, "组 1264");
        if (diagram) result.omitted_paths.push(manifestPath(diagram));
    } else {
        sizeBody = findLayer(sourceSize, ["03选尺码"]);
        sizeRect = [30, box(sizeBody)[1] + 239, 730, 442];
        sizeData = [];
        diagram = optionalClassicLayer(profile.size, "组 1264");
        if (diagram) result.omitted_paths.push(manifestPath(diagram));
    }
    var sizeEnd;
    if (profile.editableSize) sizeEnd = box(sourceSize)[3];
    else if (profile.columnLayout) sizeEnd = box(findLayer(profile.product, ["尺码快选"]))[1] - 25;
    else sizeEnd = sizeRect[1] + sizeRect[3] + 45;
    var sizeModule = manifestTable(doc, "size_table", "03选尺码", sourceSize, sizeRect, sizeBasePath, sizeData,
        {headerHeight: 65, headerMin: 32, rowHeight: 51, px: 24, accent: false},
        [10, box(sourceSize)[1], 770, sizeEnd - box(sourceSize)[1]], []);
    if (profile.editableSize) {
        sizeModule.background_paths = manifestEditableTableBackgrounds(sizeBody);
        var sizeOuter = optionalClassicLayer(sourceSize, "矩形 959 拷贝 2");
        if (sizeOuter) sizeModule.background_paths.push(manifestPath(sizeOuter));
    } else if (!profile.columnLayout) sizeModule.table.cover_rect = sizeRect.slice();
    result.modules.push(sizeModule);
    if (reportStage) reportStage("读取尺码快选布局");
    var quick, quickRect, quickBase = null, quickData, quickExtra = [];
    var trial, trialBody, trialBase, trialData;
    if (profile.columnLayout) {
        quick = findLayer(profile.product, ["尺码快选"]);
        quickBase = manifestPath(findLayer(quick, ["组 1262", "矩形 959 拷贝 4"]));
        quickRect = manifestRect(findLayer(doc, quickBase));
        var quickUnits = findLayer(quick, ["组 1004", "身高cm/体重kg"]);
        quickData = manifestRemovals(quick, [quickBase, manifestPath(quickUnits)]);
        var title = manifestDirectTitle(profile.product, /尺码快选|尺码推荐/);
        if (title) quickExtra.push(manifestPath(title));
        trial = findLayer(profile.product, ["试穿尺码", "试穿尺码 拷贝"]);
        trialBody = findLayer(trial, ["组 1154 拷贝"]);
    } else {
        if (profile.editableQuick) {
            quick = profile.editableQuick.group;
            quickBase = manifestPath(profile.editableQuick.base);
            quickRect = manifestRect(profile.editableQuick.base);
            quickData = manifestEditableTableData(quick);
        } else {
            quick = findLayer(profile.size, ["05尺码快选"]);
            var qr = manifestRect(quick);
            quickRect = [qr[0] + 22, qr[1] + 99, qr[2] - 44, qr[3] - 135];
            quickData = [];
        }
        trial = findLayer(profile.size, ["试穿尺码", "试穿尺码 拷贝"]);
        trialBody = findLayer(trial, ["组 1154 拷贝"]);
        var duplicateTrial = optionalClassicLayer(findLayer(profile.size, ["试穿尺码"]), "组 1154 拷贝");
        if (duplicateTrial) result.omitted_paths.push(manifestPath(duplicateTrial));
    }
    var quickModuleRect = manifestRect(quick);
    if (quickBase && !profile.editableQuick) quickModuleRect = quickRect.slice();
    if (quickExtra.length) quickModuleRect = manifestUnion([quickModuleRect, manifestRect(findLayer(doc, quickExtra[0]))]);
    var quickModule = manifestTable(doc, "quick_size", "05尺码快选", quick, quickRect, quickBase, quickData,
        {headerHeight: 64, headerMin: 32, rowHeight: 51, px: 22, accent: true}, quickModuleRect, quickExtra);
    if (profile.editableQuick) quickModule.background_paths = manifestEditableTableBackgrounds(quick);
    else if (!profile.columnLayout) quickModule.table.cover_rect = quickRect.slice();
    result.modules.push(quickModule);
    if (reportStage) reportStage("读取试穿报告布局");
    trialBase = manifestPath(findLayer(trialBody, ["矩形 959 拷贝 4"]));
    var trialRect = manifestRect(findLayer(doc, trialBase));
    // In this known variant the following native quick-size card overlays the
    // old trial base's empty bottom padding. Use its actual top as the limit,
    // so growing trial rows can never be hidden behind that card.
    if (profile.editableQuick && quickModuleRect[1] > trialRect[1] + 100 && quickModuleRect[1] < trialRect[1] + trialRect[3] + 18) {
        trialRect[3] = quickModuleRect[1] - trialRect[1] - 18;
    }
    trialData = manifestRemovals(trialBody, [trialBase]);
    result.modules.push(manifestTable(doc, "try_on", "试穿报告", trial, trialRect, trialBase, trialData,
        {headerHeight: 59, headerMin: 32, rowHeight: 51, px: 22, accent: true},
        [trialRect[0], box(trial)[1], trialRect[2], trialRect[1] + trialRect[3] + 18 - box(trial)[1]], []));
    if (reportStage) reportStage("读取模特图位布局");
    var sceneImages = manifestClassicSceneImages(profile);
    result.original_images = result.original_images.concat(sceneImages);
    var sceneModule = manifestModule(doc, "scenes", profile.model, null, [], []);
    var excluded = [];
    for (var i = 0; i < sceneImages.length; i++) excluded.push(sceneImages[i].path);
    sceneModule.titles = manifestTitles(profile.model, excluded, doc);
    for (i = sceneModule.titles.length - 1; i >= 0; i--) {
        if (!/模特展示|KK树|儿童户外/.test(sceneModule.titles[i].text)) {
            result.omitted_paths.push(sceneModule.titles[i].path);
            sceneModule.titles.splice(i, 1);
        }
    }
    sceneModule.slots = [];
    for (i = 0; i < profile.frames.length; i++) {
        var frame = findLayer(profile.model, [profile.frames[i], "矩形 1955"]);
        var slot = {id: "scene_" + (i + 1), path: manifestPath(frame), rect: manifestRect(frame)};
        result.view_slots[slot.id] = slot;
        sceneModule.slots.push(slot);
    }
    var sceneRects = manifestStaticRects(profile.model, excluded.concat(result.omitted_paths));
    for (i = 0; i < sceneModule.titles.length; i++) sceneRects.push(sceneModule.titles[i].rect);
    for (i = 0; i < sceneModule.slots.length; i++) sceneRects.push(sceneModule.slots[i].rect);
    sceneModule.rect = manifestPageRect(manifestUnion(sceneRects));
    var prototypeSlot = sceneModule.slots[sceneModule.slots.length - 1];
    var fourthRect = prototypeSlot.rect.slice();
    fourthRect[1] += fourthRect[3] + 80;
    result.view_slots.scene_4 = {id: "scene_4", path: null, prototype_path: prototypeSlot.path,
        prototype_rect: prototypeSlot.rect.slice(), rect: fourthRect, generated: true};
    result.modules.push(sceneModule);
    var brand = findLayer(doc, ["品牌故事"]);
    var brandImages = manifestImageData(brand, "brand");
    excluded = [];
    for (i = 0; i < brandImages.length; i++) excluded.push(brandImages[i].path);
    var brandModule = manifestModule(doc, "brand", brand, null, excluded, []);
    var brandFrame = findLayer(brand, ["矩形 998"]);
    result.view_slots.brand = {id: "brand", path: manifestPath(brandFrame), rect: manifestRect(brandFrame)};
    result.original_images = result.original_images.concat(brandImages);
    var brandRects = [manifestRect(brandFrame)];
    for (i = 0; i < brandModule.titles.length; i++) brandRects.push(brandModule.titles[i].rect);
    brandModule.rect = manifestPageRect(manifestUnion(brandRects));
    result.modules.push(brandModule);
    result.modules.push(manifestModule(doc, "footer", findLayer(doc, ["门店"]), null, [], []));
    for (i = 0; i < result.colors.slots.length; i++) result.original_images.push({path: result.colors.slots[i].image_path, role: "colors"});
    result.modules.sort(function (a, b) { return a.rect[1] - b.rect[1]; });
    return result;
}

function manifestWorkbench(doc) {
    var result = {version: 1, family: "workbench", canvas: {width: 790, height: doc.height.as("px")},
        modules: [], view_slots: {}, original_images: [], omitted_paths: [], stretch_paths: [], fields: {}};
    result.modules.push(manifestModule(doc, "header", findLayer(doc, ["T1 拷贝 2"]), [0, 0, 790, 550], [], []));
    result.modules.push({role: "hero", path: null, move_paths: [], generated: true, rect: [10, 550, 770, 2780],
        fill: [235, 245, 242], radius: 24, titles: [],
        dynamic_texts: [
            {field: "名称", rect: [51, 690, 690, 80], style: {font: "FZLTZHK--GBK1-0", size_px: 62, color: [33, 51, 48], align: "left"}},
            {field: "货号", rect: [54, 794, 680, 48], style: {font: "G8321-Medium", size_px: 34, color: [34, 118, 77], align: "left"}},
            {field: "colors", prefix: "配色  /  ", separator: " · ", rect: [52, 2949, 690, 48], style: {font: "FZLTZHK--GBK1-0", size_px: 33, color: [34, 118, 77], align: "left"}},
            {field: "尺码", prefix: "尺码  /  ", rect: [52, 3054, 690, 48], style: {font: "G8321-Medium", size_px: 33, color: [33, 51, 48], align: "left"}}
        ]});
    result.view_slots.hero = {id: "hero", path: null, rect: [28, 930, 734, 1850], generated: true, radius: 20};
    var panel = findLayer(doc, ["产品信息"]);
    var info = findLayer(panel, ["产品信息"]);
    result.modules.push(manifestModule(doc, "product", info, [10, 3427, 770, 1131], [],
        [["产品信息", "这样选更准确"], ["产品信息", "矩形 948"]]));
    var fields = ["名称", "货号", "尺码", "材质"];
    for (var i = 0; i < fields.length; i++) {
        var y = 3905 + 59 * i;
        result.fields[fields[i]] = {paths: [], generated: true, rect: [190, y - 28, 549, fields[i] === "材质" ? 129 : 42],
            label_rect: [61, y - 28, 116, 42], style: {font: "FZLTZHK--GBK1-0", size_px: fields[i] === "材质" ? 24 : 27,
                color: [33, 51, 48], align: "left"}};
    }
    var colors = findLayer(panel, ["颜色"]);
    result.colors = manifestColorBindings(doc, colors, colors, result.fields,
        {rect: [10, 4558, 770, 572], image_rect: [49, 4708, 152, 263], label_rect: [47, 5020, 156, 36]});
    result.modules.push(manifestModule(doc, "colors", colors, result.colors.rect, result.colors.data_paths, []));
    result.stretch_paths.push({path: ["产品信息", "矩形 948 拷贝"], role: "colors"});
    var keys = ["03选尺码", "05尺码快选", "试穿报告"];
    var roles = ["size_table", "quick_size", "try_on"];
    var bases = [["矩形 959 拷贝 4"], ["组 1262", "矩形 959 拷贝 4"], ["组 1263", "矩形 959 拷贝 4"]];
    var obsolete = [
        ["矩形 2101", "矩形 2107", "矩形 2107 拷贝", "矩形 2107 拷贝 2", "尺码", "组 841 拷贝 3", "组 1004",
         "组 1003", "组 1003 拷贝", "组 1003 拷贝 2", "组 1003 拷贝 3", "组 1003 拷贝 4"],
        ["组 1262", "组 841 拷贝 3", "组 1004", "身高/体重"], ["组 1263"]];
    var styles = [{headerHeight: 80, headerMin: 44, rowHeight: 54, px: 24, accent: false},
                  {headerHeight: 64, headerMin: 36, rowHeight: 65, px: 21, accent: true},
                  {headerHeight: 40, headerMin: 31, rowHeight: 35, px: 18, accent: true}];
    for (i = 0; i < keys.length; i++) {
        var expressions = [/选.*尺码|尺码表/, /尺码快选|尺码推荐/, /试穿报告/];
        var section = manifestSemanticSection(findLayer(doc, ["尺码"]), expressions[i], String(i + 3));
        var path = manifestPath(section);
        var basePath = path.concat(bases[i]);
        var data = [];
        for (var j = 0; j < obsolete[i].length; j++) {
            var child = findLayer(section, [obsolete[i][j]]);
            if (manifestPrefix(basePath, manifestPath(child))) data = data.concat(manifestRemovals(child, [basePath]));
            else data.push(manifestPath(child));
        }
        if (i === 1) {
            var units = findLayer(section, ["组 1004", "身高cm/体重kg"]);
            data = [];
            for (j = 0; j < obsolete[i].length; j++) data = data.concat(manifestRemovals(findLayer(section, [obsolete[i][j]]), [basePath, manifestPath(units)]));
        }
        var outer = findLayer(section, [i === 0 ? "矩形 959 拷贝 3" : "矩形 959 拷贝 2"]);
        var tableModule = manifestTable(doc, roles[i], keys[i], section, manifestRect(findLayer(doc, basePath)),
            basePath, data, styles[i], manifestRect(outer), []);
        tableModule.background_paths = [manifestPath(outer)];
        result.modules.push(tableModule);
    }
    var model = findLayer(doc, ["17.模特展示"]);
    var images = manifestImageData(model, "scenes");
    var exclusions = [];
    for (i = 0; i < images.length; i++) exclusions.push(images[i].path);
    var sceneModule = manifestModule(doc, "scenes", model, null, exclusions, []);
    sceneModule.slots = [];
    for (i = 0; i < workbenchModelPaths.length; i++) {
        var frame = findLayer(model, workbenchModelPaths[i]);
        var slot = {id: "scene_" + (i + 1), path: manifestPath(frame), rect: manifestRect(frame)};
        result.view_slots[slot.id] = slot;
        sceneModule.slots.push(slot);
    }
    var sceneRects = manifestStaticRects(model, exclusions);
    for (i = 0; i < sceneModule.titles.length; i++) sceneRects.push(sceneModule.titles[i].rect);
    for (i = 0; i < sceneModule.slots.length; i++) sceneRects.push(sceneModule.slots[i].rect);
    sceneModule.rect = manifestPageRect(manifestUnion(sceneRects));
    result.original_images = result.original_images.concat(images);
    result.modules.push(sceneModule);
    result.modules.push(manifestModule(doc, "footer", findLayer(doc, ["19.门店"]), null, [], []));
    return result;
}

function manifestFindModule(profile, role) {
    for (var i = 0; i < profile.modules.length; i++) if (profile.modules[i].role === role) return profile.modules[i];
    return null;
}

function manifestVisiblePath(doc, path) {
    // Check visibility while resolving the recorded path. Walking Photoshop's
    // parent links for this check can hang when those links do not reach the document.
    var parent = doc;
    for (var i = 0; i < path.length; i++) {
        if (parent.typename !== "LayerSet" && parent.typename !== "Document") return false;
        var children = parent.layers;
        var found = null;
        for (var j = 0, count = children.length; j < count; j++) {
            var child = children[j];
            if (child.name !== path[i]) continue;
            if (found) return false;
            found = child;
        }
        if (!found || !found.visible) return false;
        parent = found;
    }
    return true;
}

function manifestResolvePaths(doc, path) {
    var parents = [doc];
    for (var i = 0; i < path.length; i++) {
        var matches = [];
        for (var j = 0; j < parents.length; j++) {
            var parent = parents[j];
            if (!parent.layers) continue;
            for (var k = 0; k < parent.layers.length; k++) {
                if (parent.layers[k].name === path[i]) matches.push(parent.layers[k]);
            }
        }
        parents = matches;
    }
    return parents;
}

function manifestDeletePaths(doc, paths) {
    paths = paths.slice();
    paths.sort(function (a, b) { return b.length - a.length; });
    var removed = [];
    for (var i = 0; i < paths.length; i++) {
        var skip = false;
        for (var j = 0; j < removed.length; j++) if (manifestPrefix(paths[i], removed[j])) skip = true;
        if (skip) continue;
        var matches = manifestResolvePaths(doc, paths[i]);
        for (var matchIndex = matches.length - 1; matchIndex >= 0; matchIndex--) matches[matchIndex].remove();
        removed.push(paths[i]);
    }
}

function clearManifestData(doc, profile, createCovers) {
    var paths = [];
    for (var omission = 0; omission < profile.omitted_paths.length; omission++) {
        var path = profile.omitted_paths[omission];
        if (createCovers === false && profile.product_attributes &&
            manifestJson(path) === manifestJson(profile.product_attributes.path)) continue;
        paths.push(path);
    }
    for (var field in profile.fields) paths = paths.concat(profile.fields[field].paths);
    paths = paths.concat(profile.colors.data_paths);
    for (var i = 0; i < profile.modules.length; i++) {
        var module = profile.modules[i];
        if (module.table) paths = paths.concat(module.table.data_paths);
    }
    for (i = 0; i < profile.original_images.length; i++) paths.push(profile.original_images[i].path);
    manifestDeletePaths(doc, paths);
    if (createCovers === false) return;
    for (i = 0; i < profile.modules.length; i++) {
        module = profile.modules[i];
        if (module.table && module.table.cover_rect) {
            var parent = findLayer(doc, module.table.parent_path);
            var area = module.table.cover_rect;
            var cover = parent.layerSets.add();
            cover.name = "旧表格内芯遮罩 · " + module.role;
            rectangle(doc, cover, "清空原单元格", area[0], area[1], area[2], area[3], [255, 255, 255], 0);
        }
    }
}

function saveManifestPage(doc, output) {
    var preview = doc.duplicate("母版完整预览", true);
    try {
        preview.flatten();
        preview.resizeImage(UnitValue(790, "px"), null, null, ResampleMethod.BICUBICSHARPER);
        var options = new JPEGSaveOptions();
        options.quality = 10;
        preview.saveAs(new File(output), options, true, Extension.LOWERCASE);
    } finally { preview.close(SaveOptions.DONOTSAVECHANGES); }
}

function saveManifestMask(doc, slot, output) {
    var frame = slot.rect;
    var maskDoc = app.documents.add(UnitValue(Math.ceil(frame[2]), "px"), UnitValue(Math.ceil(frame[3]), "px"),
        doc.resolution, "图位蒙版", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    try {
        if (slot.path || slot.prototype_path) {
            app.activeDocument = doc;
            var copy = findLayer(doc, slot.path || slot.prototype_path).duplicate(maskDoc, ElementPlacement.PLACEATBEGINNING);
            app.activeDocument = maskDoc;
            if (copy.grouped) copy.grouped = false;
            // Photoshop recenters a cross-document duplicate. The source-page
            // coordinates are no longer the copy's coordinates in this document.
            // Keep the native vector/user masks and make their silhouette visible.
            copy.visible = true;
            copy.opacity = 100;
            copy.fillOpacity = 100;
            var actual = box(copy);
            copy.translate(UnitValue(-actual[0], "px"), UnitValue(-actual[1], "px"));
        } else {
            var group = maskDoc.layerSets.add();
            rectangle(maskDoc, group, "图位", 0, 0, frame[2], frame[3], [255, 255, 255], slot.radius || 0);
        }
        maskDoc.saveAs(new File(output), new PNGSaveOptions(), true, Extension.LOWERCASE);
    } finally {
        maskDoc.close(SaveOptions.DONOTSAVECHANGES);
        app.activeDocument = doc;
    }
}

function repairManifestMasks(spec) {
    var units = app.preferences.rulerUnits;
    var dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc;
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        doc = app.open(new File(spec.source));
        for (var key in spec.profile.view_slots) {
            if (key === "measurement") continue;
            saveManifestMask(doc, spec.profile.view_slots[key], spec.assetsFolder + "/mask-" + key + ".png");
        }
    } finally {
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) { try { app.activeDocument = prior; } catch (priorError) {} }
    }
}

function manifestMaskClippedForeground(doc, layer, frame) {
    var savedChannels = doc.activeChannels;
    var key = charIDToTypeID;
    try {
        doc.activeLayer = frame;
        var select = new ActionDescriptor();
        var destination = new ActionReference();
        destination.putProperty(key("Chnl"), key("fsel"));
        select.putReference(key("null"), destination);
        var transparency = new ActionReference();
        transparency.putEnumerated(key("Chnl"), key("Chnl"), key("Trsp"));
        select.putReference(key("T   "), transparency);
        executeAction(key("setd"), select, DialogModes.NO);
        try { var selectionBounds = doc.selection.bounds; } catch (emptySelectionError) {
            throw new Error("固定前景的原图框剪贴范围为空：" + frame.name);
        }
        doc.activeLayer = layer;
        layer.grouped = false;
        var reference = new ActionReference();
        reference.putProperty(stringIDToTypeID("property"), stringIDToTypeID("hasUserMask"));
        reference.putIdentifier(stringIDToTypeID("layer"), layer.id);
        var descriptor = executeActionGet(reference);
        if (descriptor.hasKey(stringIDToTypeID("hasUserMask")) && descriptor.getBoolean(stringIDToTypeID("hasUserMask"))) {
            var mask = new ActionDescriptor();
            var channel = new ActionReference();
            channel.putEnumerated(key("Chnl"), key("Chnl"), key("Msk "));
            mask.putReference(key("null"), channel);
            executeAction(key("slct"), mask, DialogModes.NO);
            doc.selection.invert();
            doc.selection.fill(rgb([0, 0, 0]), ColorBlendMode.NORMAL, 100, false);
        } else {
            var make = new ActionDescriptor();
            make.putClass(key("Nw  "), key("Chnl"));
            var location = new ActionReference();
            location.putEnumerated(key("Chnl"), key("Chnl"), key("Msk "));
            make.putReference(key("At  "), location);
            make.putEnumerated(key("Usng"), key("UsrM"), key("RvlS"));
            executeAction(key("Mk  "), make, DialogModes.NO);
        }
    } finally {
        doc.selection.deselect();
        doc.activeChannels = savedChannels;
    }
}

function manifestKeepAboveFrame(parent, path, depth, doc) {
    var target = findLayer(parent, [path[depth]]);
    var index = -1;
    for (var i = 0; i < parent.layers.length; i++) if (parent.layers[i].id === target.id) index = i;
    if (index < 0) throw new Error("未定位前景的真实图框层：" + path.join(" / "));
    for (i = 0; i < index; i++) {
        var upper = parent.layers[i];
        if (!upper.visible || !upper.grouped) continue;
        var baseIndex = i + 1;
        while (baseIndex < parent.layers.length && parent.layers[baseIndex].grouped) baseIndex++;
        if (baseIndex >= index) {
            if (baseIndex !== index || depth !== path.length - 1) {
                throw new Error("固定前景的剪贴依赖暂未识别：" + manifestPath(upper).join(" / "));
            }
            // Preserve this layer's own native clipping; unrelated green curves
            // remain free to cross the frame corners, as they do in Photoshop.
            manifestMaskClippedForeground(doc, upper, target);
        }
    }
    for (i = index + 1; i < parent.layers.length; i++) parent.layers[i].visible = false;
    if (depth === path.length - 1) target.visible = false;
    else manifestKeepAboveFrame(target, path, depth + 1, doc);
}

function saveManifestForeground(doc, slot, output) {
    if (!slot.path) return false;
    var capture;
    var frame = slot.rect;
    try {
        app.activeDocument = doc;
        capture = doc.duplicate("图位固定前景", false);
        manifestKeepAboveFrame(capture, slot.path, 0, capture);
        slot.foreground_layers = [];
        function recordVisible(parent) {
            for (var i = 0; i < parent.layers.length; i++) {
                var layer = parent.layers[i];
                if (!layer.visible) continue;
                if (layer.typename === "LayerSet") {
                    var countBefore = slot.foreground_layers.length;
                    recordVisible(layer);
                    if (slot.foreground_layers.length > countBefore && layer.blendMode !== BlendMode.NORMAL &&
                        String(layer.blendMode) !== "BlendMode.PASSTHROUGH") {
                        throw new Error("无法等价提取非普通混合的前景父组：" + manifestPath(layer).join(" / "));
                    }
                    continue;
                }
                var bounds = box(layer);
                if (bounds[0] >= frame[0] + frame[2] || bounds[2] <= frame[0] ||
                    bounds[1] >= frame[1] + frame[3] || bounds[3] <= frame[1]) continue;
                if (layer.blendMode !== BlendMode.NORMAL) {
                    throw new Error("无法等价提取非普通混合的固定前景：" + manifestPath(layer).join(" / "));
                }
                slot.foreground_layers.push(manifestPath(layer));
            }
        }
        recordVisible(capture);
        capture.crop([UnitValue(frame[0], "px"), UnitValue(frame[1], "px"),
                      UnitValue(frame[0] + frame[2], "px"), UnitValue(frame[1] + frame[3], "px")]);
        capture.saveAs(new File(output), new PNGSaveOptions(), true, Extension.LOWERCASE);
        return true;
    } finally {
        if (capture) { try { capture.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        app.activeDocument = doc;
    }
}

function exportManifestForegrounds(clean, profile, assetsFolder, reportStage) {
    for (var key in profile.view_slots) {
        var slot = profile.view_slots[key];
        if (slot.foreground) delete slot.foreground;
        if (!slot.path || key === "measurement") continue;
        if (reportStage) reportStage("导出图位固定前景 " + key);
        var output = assetsFolder + "/foreground-" + key + ".png";
        saveManifestForeground(clean, slot, output);
        slot.foreground = output;
    }
    profile.foreground_version = 1;
}

// These native shapes are removable photo decorations. Do not infer a removable
// layer from a pixel color, a generic layer name or a nearby brand mark.
var manifestDecorationPaths = [
    ["17.模特展示", "形状 1241"],
    ["模特", "组 1113 拷贝", "形状 4120"]
];

function manifestDecorationId(path) {
    var value = path.join("\u001f");
    var hash = 0;
    for (var i = 0; i < value.length; i++) hash = (hash * 31 + value.charCodeAt(i)) | 0;
    return "decoration-" + ("00000000" + (hash >>> 0).toString(16)).slice(-8);
}

function manifestVisibleDecoration(layer) {
    if (layer.typename !== "ArtLayer" || layer.grouped || String(layer.blendMode) !== "BlendMode.NORMAL") return false;
    var kind = String(layer.kind);
    if (kind !== "LayerKind.GRADIENTFILL" && kind !== "LayerKind.SOLIDFILL") return false;
    for (var ancestor = layer; ancestor.typename !== "Document"; ancestor = ancestor.parent) {
        if (!ancestor.visible || ancestor.grouped) return false;
        var mode = String(ancestor.blendMode);
        if (mode !== "BlendMode.NORMAL" && mode !== "BlendMode.PASSTHROUGH") return false;
    }
    return true;
}

function manifestIsolateDecoration(parent, path, depth) {
    var target = findLayer(parent, [path[depth]]);
    for (var i = 0; i < parent.layers.length; i++) {
        var other = parent.layers[i];
        if (other.id !== target.id && other.visible) other.visible = false;
    }
    if (depth + 1 < path.length) manifestIsolateDecoration(target, path, depth + 1);
}

function exportManifestDecorations(clean, profile, assetsFolder) {
    profile.decorations = [];
    profile.decoration_version = 1;
    var module = manifestFindModule(profile, "scenes");
    if (!module) return;
    for (var i = 0; i < manifestDecorationPaths.length; i++) {
        var path = manifestDecorationPaths[i];
        var matches = manifestResolvePaths(clean, path);
        if (matches.length !== 1 || !manifestVisibleDecoration(matches[0])) continue;
        var bounds = box(matches[0]);
        var scene = module.rect;
        var left = Math.max(0, Math.floor(scene[0]), Math.floor(bounds[0]));
        var top = Math.max(0, Math.floor(scene[1]), Math.floor(bounds[1]));
        var right = Math.min(profile.canvas.width, Math.ceil(scene[0] + scene[2]), Math.ceil(bounds[2]));
        var bottom = Math.min(profile.canvas.height, Math.ceil(scene[1] + scene[3]), Math.ceil(bounds[3]));
        if (left >= right || top >= bottom) continue;
        var id = manifestDecorationId(path);
        var output = assetsFolder + "/" + id + ".png";
        var isolated = null;
        try {
            app.activeDocument = clean;
            isolated = clean.duplicate("可移除的绿线装饰", false);
            manifestIsolateDecoration(isolated, path, 0);
            isolated.crop([UnitValue(left, "px"), UnitValue(top, "px"),
                           UnitValue(right, "px"), UnitValue(bottom, "px")]);
            isolated.saveAs(new File(output), new PNGSaveOptions(), true, Extension.LOWERCASE);
        } finally {
            if (isolated) isolated.close(SaveOptions.DONOTSAVECHANGES);
            app.activeDocument = clean;
        }
        matches[0].visible = false;
        profile.decorations.push({id: id, label: "绿线装饰", role: "scenes", path: path,
                                  rect: [left, top, right - left, bottom - top], image: output});
    }
}

function exportManifestMeasurement(doc, profile, assetsFolder) {
    var slot = profile.view_slots.measurement;
    if (!slot) return;
    var layer = findLayer(doc, slot.path);
    var frame = slot.rect;
    var isolated = app.documents.add(UnitValue(frame[2], "px"), UnitValue(frame[3], "px"),
        doc.resolution, "尺码测量示意图", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    try {
        app.activeDocument = doc;
        var original = box(layer);
        var copy = layer.duplicate(isolated, ElementPlacement.PLACEATBEGINNING);
        app.activeDocument = isolated;
        var actual = box(copy);
        copy.translate(UnitValue(original[0] - frame[0] - actual[0], "px"),
                       UnitValue(original[1] - frame[1] - actual[1], "px"));
        slot.original = assetsFolder + "/measurement-original.png";
        isolated.saveAs(new File(slot.original), new PNGSaveOptions(), true, Extension.LOWERCASE);
    } finally {
        isolated.close(SaveOptions.DONOTSAVECHANGES);
        app.activeDocument = doc;
    }
    layer.visible = false;
}

function repairManifestPreviewAssets(spec) {
    var units = app.preferences.rulerUnits;
    var dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc;
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        doc = app.open(new File(spec.source));
        var classic = classicTemplateProfile(doc);
        if (classic) {
            var retained = [];
            for (var imageIndex = 0; imageIndex < spec.profile.original_images.length; imageIndex++) {
                if (spec.profile.original_images[imageIndex].role !== "scenes") retained.push(spec.profile.original_images[imageIndex]);
            }
            spec.profile.original_images = retained.concat(manifestClassicSceneImages(classic));
        }
        delete spec.profile.view_slots.measurement;
        bindManifestMeasurement(doc, spec.profile, classic);
        delete spec.profile.size_note;
        bindManifestSizeNote(doc, spec.profile);
        for (var key in spec.profile.view_slots) {
            if (key === "measurement") continue;
            var slot = spec.profile.view_slots[key];
            slot.mask = spec.assetsFolder + "/mask-" + key + ".png";
            saveManifestMask(doc, slot, slot.mask);
        }
        exportManifestMeasurement(doc, spec.profile, spec.assetsFolder);
        hideManifestSizeNote(doc, spec.profile);
        clearManifestData(doc, spec.profile);
        exportManifestDecorations(doc, spec.profile, spec.assetsFolder);
        spec.profile.clean_preview = spec.assetsFolder + "/clean.jpg";
        saveManifestPage(doc, spec.profile.clean_preview);
        exportManifestForegrounds(doc, spec.profile, spec.assetsFolder);
        spec.profile.mask_version = 2;
        manifestWrite(spec.profileOutput, spec.profile);
    } finally {
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) { try { app.activeDocument = prior; } catch (priorError) {} }
    }
}

function extractManifestAssets(doc, spec, classic, sections, classified) {
    var stage = "识别母版布局";
    function setStage(name) {
        stage = name;
        templateImportStage(spec, name);
    }
    try {
    setStage("识别母版布局");
    if (!classified) classified = classifyTemplateDocument(doc, spec);
    classic = classified.family === "classic" ? classified.bindings : null;
    sections = classified.family === "section" ? classified.bindings : null;
    var profile;
    if (classic) profile = manifestClassic(doc, classic, setStage);
    else if (sections) profile = manifestSectionTemplate(doc, sections, setStage);
    else if (classified.family === "workbench") profile = manifestWorkbench(doc);
    else throw new Error("母版尚未整理为可套版结构，请重新上传原稿。");
    if (sections && spec.sectionImportWarnings) {
        profile.import_warnings = (profile.import_warnings || []).concat(spec.sectionImportWarnings);
    }
    setStage("识别量体图");
    bindManifestMeasurement(doc, profile, classic, setStage);
    setStage("识别尺码备注");
    bindManifestSizeNote(doc, profile);
    setStage("整理母版文字");
    profile.unreadable_text_paths = [];
    for (var moduleIndex = 0; moduleIndex < profile.modules.length; moduleIndex++) {
        var fixedTitles = profile.modules[moduleIndex].titles;
        for (var titleIndex = fixedTitles.length - 1; titleIndex >= 0; titleIndex--) {
            if (manifestExcluded(fixedTitles[titleIndex].path, profile.omitted_paths)) {
                fixedTitles.splice(titleIndex, 1);
                continue;
            }
            if (fixedTitles[titleIndex].unreadable_style) profile.unreadable_text_paths.push(fixedTitles[titleIndex].path);
        }
    }
    profile.original_preview = spec.originalPreview;
    profile.working_preview = spec.workingPreview || spec.originalPreview;
    if (spec.sourceCanvas) profile.source_canvas = {width: spec.sourceCanvas[0], height: spec.sourceCanvas[1]};
    profile.clean_preview = spec.cleanPreview;
    profile.mask_version = 2;
    for (var key in profile.view_slots) {
        if (key === "measurement") continue;
        var slot = profile.view_slots[key];
        slot.mask = spec.assetsFolder + "/mask-" + key + ".png";
        slot.mask_rect = slot.rect.slice();
        setStage("导出图位蒙版 " + key);
        saveManifestMask(doc, slot, slot.mask);
    }
    if (spec.sourceIsWorking !== false && !spec.originalPreviewReady) {
        setStage("导出完整母版原稿参考");
        snapshotReferenceDocument(doc, spec.originalPreview);
    }
    setStage("导出工作母版预览");
    saveManifestPage(doc, profile.working_preview);
    setStage("提取 STEP1 属性组件");
    exportManifestProductAttributes(doc, profile, spec.assetsFolder);
    setStage("准备清理母版动态内容");
    var clean = doc.duplicate("母版静态装饰", false);
    try {
        setStage("提取尺码测量示意图");
        exportManifestMeasurement(clean, profile, spec.assetsFolder);
        hideManifestSizeNote(clean, profile);
        setStage("清理动态内芯");
        clearManifestData(clean, profile);
        setStage("提取可移除的绿线装饰");
        exportManifestDecorations(clean, profile, spec.assetsFolder);
        setStage("导出静态装饰预览");
        saveManifestPage(clean, spec.cleanPreview);
        setStage("导出图位固定前景");
        exportManifestForegrounds(clean, profile, spec.assetsFolder, setStage);
    } finally {
        clean.close(SaveOptions.DONOTSAVECHANGES);
        app.activeDocument = doc;
    }
    setStage("写入母版布局记录");
    manifestWrite(spec.profileOutput, profile);
    return profile;
    } catch (error) {
        throw new Error(stage + "失败，原第 " + error.line + " 行：" + error.message);
    }
}
